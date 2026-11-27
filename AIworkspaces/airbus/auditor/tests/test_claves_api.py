"""
Pruebas de src/claves_api.py: crear, comprobar, caducar, revocar, alcances y permisos de las claves de API.

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_claves_api -v
"""
import json
import unittest
from datetime import datetime, timedelta

from src import claves_api as CA
from src import permisos as P

AHORA = datetime(2026, 11, 27, 10, 0, 0)


def estado():
    e = {"equipo": [{"n": "Ana", "c": "ana@x", "rol": "admin"}, {"n": "Mar", "c": "mar@x", "rol": "aprobador"},
                    {"n": "Rui", "c": "rui@x", "rol": "revisor"}, {"n": "Pau", "c": "pau@x", "rol": "dueno_proceso"}]}
    P.migrar(e)
    return e


class Crear(unittest.TestCase):
    def test_quien_puede_crear(self):
        e = estado()
        for u in ("Ana", "Mar"):
            clave, pub = CA.crear(e, u, "Power BI", 90, ["metricas"], AHORA)
            self.assertTrue(clave.startswith("nas_") and len(clave) > 40)
        for u in ("Rui", "Pau"):                      # Revisor y Dueño de Proceso: sin «Usar la API»
            with self.assertRaises(P.Denegado):
                CA.crear(e, u, "x", 90, ["metricas"], AHORA)

    def test_solo_se_guarda_la_huella(self):
        e = estado()
        clave, pub = CA.crear(e, "Mar", "Excel", 30, ["documentos", "hallazgos"], AHORA)
        texto = json.dumps(e)
        self.assertNotIn(clave, texto)                # la clave en claro no queda en ningún sitio
        self.assertNotIn("huella", pub)
        self.assertEqual(pub["prefijo"], clave[:12])
        self.assertEqual(pub["caduca"], (AHORA + timedelta(days=30)).isoformat(timespec="seconds"))

    def test_validaciones(self):
        e = estado()
        for nombre, dias, alc in (("", 90, ["metricas"]), ("x", 45, ["metricas"]), ("x", 90, []), ("x", 90, ["todo"])):
            with self.assertRaises(P.Denegado):
                CA.crear(e, "Mar", nombre, dias, alc, AHORA)

    def test_no_mas_alcance_que_el_rol(self):
        e = estado()
        rol = next(r for r in e["roles"] if r["id"] == "aprobador")
        rol["permisos"]["metricas"]["consultar"] = False
        with self.assertRaises(P.Denegado):
            CA.crear(e, "Mar", "x", 90, ["metricas"], AHORA)

    def test_maximo_de_activas(self):
        e = estado()
        for i in range(CA.MAX_ACTIVAS):
            CA.crear(e, "Mar", f"c{i}", 30, ["metricas"], AHORA)
        with self.assertRaises(P.Denegado):
            CA.crear(e, "Mar", "una más", 30, ["metricas"], AHORA)


class Verificar(unittest.TestCase):
    def setUp(self):
        self.e = estado()
        self.clave, self.pub = CA.crear(self.e, "Mar", "Power BI", 90, ["metricas", "documentos"], AHORA)

    def codigo(self, clave, alcance="metricas", ahora=AHORA):
        try:
            CA.verificar(self.e, clave, alcance, ahora)
            return 200
        except P.Denegado as ex:
            return ex.code

    def test_valida(self):
        self.assertEqual(self.codigo(self.clave), 200)
        self.assertEqual(self.codigo(self.clave, "documentos"), 200)

    def test_falsa_o_ausente(self):
        self.assertEqual(self.codigo(""), 401)
        self.assertEqual(self.codigo("nas_inventada"), 401)
        self.assertEqual(self.codigo(self.clave[:-1] + ("A" if self.clave[-1] != "A" else "B")), 401)

    def test_alcance(self):
        self.assertEqual(self.codigo(self.clave, "hallazgos"), 403)

    def test_caduca(self):
        self.assertEqual(self.codigo(self.clave, ahora=AHORA + timedelta(days=90)), 401)

    def test_revocada(self):
        CA.revocar(self.e, "Mar", self.pub["id"], AHORA)
        self.assertEqual(self.codigo(self.clave), 401)

    def test_pierde_el_permiso_o_deja_el_equipo(self):
        rol = next(r for r in self.e["roles"] if r["id"] == "aprobador")
        rol["permisos"]["api"]["usar"] = False
        self.assertEqual(self.codigo(self.clave), 403)
        rol["permisos"]["api"]["usar"] = True
        rol["permisos"]["metricas"]["consultar"] = False
        self.assertEqual(self.codigo(self.clave), 403)
        self.e["equipo"] = [m for m in self.e["equipo"] if m["n"] != "Mar"]
        self.assertEqual(self.codigo(self.clave), 401)


class RevocarYListar(unittest.TestCase):
    def test_quien_revoca_y_quien_ve(self):
        e = estado()
        _, pm = CA.crear(e, "Mar", "de Mar", 90, ["metricas"], AHORA)
        _, pa = CA.crear(e, "Ana", "de Ana", 90, ["metricas"], AHORA)
        with self.assertRaises(P.Denegado):
            CA.revocar(e, "Rui", pm["id"], AHORA)     # ni su dueño ni Admin
        self.assertEqual([c["nombre"] for c in CA.listar(e, "Mar", AHORA)], ["de Mar"])
        self.assertEqual(len(CA.listar(e, "Ana", AHORA)), 2)    # el Admin ve todas
        CA.revocar(e, "Ana", pm["id"], AHORA)          # y puede revocar cualquiera
        self.assertEqual(CA.listar(e, "Mar", AHORA)[0]["estado"], "revocada")

    def test_registro_de_uso(self):
        e = estado()
        _, pub = CA.crear(e, "Mar", "x", 90, ["metricas"], AHORA)
        reg = e["claves_api"][pub["id"]]
        CA.registrar_uso(e, reg, "/api/v1/metricas/resumen", 200, AHORA)
        self.assertEqual((reg["usos"], reg["ultimo_uso"]), (1, AHORA.isoformat(timespec="seconds")))
        self.assertEqual(e["api_uso"][-1]["codigo"], 200)


class Permiso(unittest.TestCase):
    def test_roles_guardados_antes(self):
        e = estado()
        for r in e["roles"]:
            r["permisos"].pop("api", None)            # como si se hubieran guardado antes de existir la API
        P.migrar(e)
        self.assertTrue(P.puede(e, "Ana", "api", "usar"))
        self.assertTrue(P.puede(e, "Mar", "api", "usar"))
        self.assertFalse(P.puede(e, "Rui", "api", "usar"))
        self.assertFalse(P.puede(e, "Pau", "api", "usar"))


if __name__ == "__main__":
    unittest.main()
