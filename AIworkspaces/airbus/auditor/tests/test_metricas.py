"""
Pruebas de src/metricas.py con un escenario pequeño cuyas cifras se saben de antemano.

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_metricas -v
"""
import unittest
from datetime import date

from src import metricas as M

HOY = date(2026, 11, 20)
DOCS = {"A": {"familia": "Especificaciones", "titulo": "Doc A", "version": "1.0"},
        "B": {"familia": "Registros", "titulo": "Doc B", "version": "1.0"},
        "C": {"familia": "Registros", "titulo": "Doc C", "version": "1.0"},     # sin hallazgos
        "Z": {"familia": "Registros", "titulo": "Doc Z", "version": "1.0"}}     # sin hallazgos, revisado


def h(doc, u, tipo="No cumple", clausula="IS.I.OR.200", conf=0.8, origen="regla R1"):
    return {"documento": doc, "ubicacion": u, "tipo": tipo, "clausula": clausula, "conf": conf, "origen": origen}


RES = [h("A", f"R{i}") for i in range(1, 6)] + [h("A", "R6", "No verificable", "IS.I.OR.230", 0.95, "llm"),
                                                h("B", "R1", "Inconsistencia", "IS.I.OR.230", 0.65)]


def estado():
    return {"dec": {"A|R1": {"dec": "approved", "user": "Ana", "fecha": "2026-11-12T10:00:00"},
                    "A|R2": {"dec": "rejected", "user": "Rui", "fecha": "2026-11-15T10:00:00"},
                    "A|R6": {"dec": "approved", "user": "Ana", "fecha": "2026-11-19T10:00:00"}},
            "comentarios": [{"key": "A|R1", "user": "Rui", "fecha": "2026-11-18T09:00:00"},
                            {"key": "B|R1", "user": "Ana", "fecha": "2026-10-01T09:00:00"}],
            "ediciones": {"A|R3": [{"user": "Rui", "fecha": "2026-11-13T09:00:00"}]},
            "docs_meta": {"Z": {"revisado": {"user": "Ana", "fecha": "2026-11-14"}}},
            "config": {"plazo_dias": 15, "inicio": "2026-11-01"},
            "escalados": {"B": {"para": "Pau", "por": "Ana", "fecha": "2026-11-16T09:00:00"}},
            "escalados_hist": [{"doc": "A", "accion": "escalar", "para": "Pau", "por": "Ana", "fecha": "2026-11-10T09:00:00"},
                               {"doc": "A", "accion": "corregir", "para": "Pau", "por": "Pau", "fecha": "2026-11-13T09:00:00"},
                               {"doc": "B", "accion": "escalar", "para": "Pau", "por": "Ana", "fecha": "2026-11-16T09:00:00"}],
            "versiones": {"A": [{"n": 1, "user": "Pau", "fecha": "2026-11-13T09:00:00"}]}}


CARGADOS = [{"clave": "UP-1", "familia": "Especificaciones", "titulo": "Cargado", "prioridad": "Baja", "fecha": "2026-11-18T09:00:00"}]


def calc(**f):
    return M.calcular(RES, DOCS, estado(), CARGADOS, f, HOY, {"f1": "0,9"})


class Documentos(unittest.TestCase):
    def test_estado_prioridad_y_dias(self):
        d = {x["doc"]: x for x in M.documentos(RES, DOCS, estado(), CARGADOS, HOY)}
        self.assertEqual(d["A"]["estado"], "En revisión")
        self.assertEqual(d["A"]["prioridad"], "Alta")             # 5 «No cumple»
        self.assertEqual(d["A"]["dias"], {"tipo": "dias", "n": -4, "pasados": 19})   # 15 - 19 → vencido
        self.assertEqual(d["B"]["prioridad"], "Media")
        self.assertEqual(d["C"]["estado"], "Sin hallazgos")
        self.assertEqual(d["C"]["dias"], {"tipo": "na"})
        self.assertEqual(d["Z"]["estado"], "Completado")          # sin hallazgos, marcado como revisado
        self.assertEqual(d["UP-1"]["prioridad"], "Baja")
        self.assertEqual(d["UP-1"]["dias"]["n"], 13)               # cargado el 18: 15 - 2
        self.assertTrue(d["UP-1"]["necesita"])


class Resumen(unittest.TestCase):
    def test_kpis(self):
        k = calc()["resumen"]["kpis"]
        self.assertEqual((k["documentos"], k["hallazgos"], k["decididos"]), (5, 7, 3))
        self.assertEqual(k["pct_decididos"], 42.9)
        self.assertEqual((k["vencidos"], k["vencen_3"]), (2, 0))        # A y B vencidos (inicio 1-nov)
        self.assertEqual(k["no_cumple_abiertos"], 3)                     # A|R3, R4, R5
        self.assertEqual(k["por_revisar"], 3)                            # A, B y el cargado
        self.assertEqual(k["devueltos"], 1)

    def test_serie_y_atencion(self):
        r = calc()["resumen"]
        self.assertEqual(r["serie"][0], {"fecha": "2026-11-01", "pendientes": 7, "ritmo": 7.0})
        dia = {p["fecha"]: p for p in r["serie"]}
        self.assertEqual(dia["2026-11-20"]["pendientes"], 4)            # 3 decididas antes del 20
        self.assertIsNone(dia.get("2026-11-21", {"pendientes": None})["pendientes"])
        self.assertEqual(dia["2026-11-16"]["ritmo"], 0.0)               # fin del plazo
        self.assertEqual([a["doc"] for a in r["atencion"]], ["A", "B", "UP-1"])   # Alta, luego Media, luego Baja


class Filtros(unittest.TestCase):
    def test_familia_y_tipo(self):
        k = calc(familia="Registros")["resumen"]["kpis"]
        self.assertEqual((k["documentos"], k["hallazgos"]), (3, 1))
        k = calc(tipo="No cumple")["resumen"]["kpis"]
        self.assertEqual((k["documentos"], k["hallazgos"]), (1, 5))
        self.assertEqual(calc(clausula="IS.I.OR.230")["resumen"]["kpis"]["hallazgos"], 2)
        self.assertEqual(calc(prioridad="Baja")["resumen"]["kpis"]["documentos"], 3)   # C, Z y el cargado

    def test_periodo_acota_la_actividad(self):
        self.assertEqual(calc()["equipo"]["kpis"]["decisiones"], 3)
        e = calc(periodo="7")["equipo"]["kpis"]
        self.assertEqual(e["decisiones"], 2)                             # 15 y 19 de noviembre
        self.assertEqual(e["comentarios"], 1)
        self.assertEqual(len(calc(periodo="7")["equipo"]["serie_decisiones"]), 7)


class Cumplimiento(unittest.TestCase):
    def test_tipos_clausulas_y_mapa(self):
        c = calc()["cumplimiento"]
        self.assertEqual(c["por_tipo"][0], {"tipo": "No cumple", "n": 5, "abiertos": 3})
        self.assertEqual(c["por_clausula"][0], {"clausula": "IS.I.OR.200", "n": 5})
        m = c["mapa"]
        self.assertEqual(m["celdas"][m["familias"].index("Registros")][m["clausulas"].index("IS.I.OR.230")], 1)
        self.assertEqual([x["doc"] for x in c["alta_sin_revisar"]], ["A"])


class Equipo(unittest.TestCase):
    def test_tiempos(self):
        e = calc()["equipo"]["kpis"]
        self.assertEqual(e["dias_medios_decidir"], 14.3)                 # (11 + 14 + 18) / 3
        self.assertEqual((e["devoluciones"], e["correcciones"], e["dias_medios_corregir"]), (2, 1, 3.0))
        self.assertEqual((e["versiones"], e["bloqueados"]), (1, 1))


class CalidadIA(unittest.TestCase):
    def test_acuerdo(self):
        ia = calc()["ia"]
        self.assertEqual(ia["acuerdo"], {"aceptados": 2, "rechazados": 1, "sin_decidir": 4, "pct_acuerdo": 66.7})
        self.assertEqual({o["origen"]: o["pct_acuerdo"] for o in ia["por_origen"]}, {"regla": 50.0, "llm": 100.0})
        self.assertEqual([t["tramo"] for t in ia["por_confianza"]], ["0,6–0,7", "0,8–0,9", "≥ 0,9"])
        self.assertEqual(ia["editados"], {"n": 1, "total": 7, "pct": 14.3})
        self.assertEqual(ia["metricas"], {"f1": "0,9"})


if __name__ == "__main__":
    unittest.main()
