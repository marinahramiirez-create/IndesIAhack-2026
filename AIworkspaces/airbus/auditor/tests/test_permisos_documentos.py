"""
Pruebas de los permisos de documentos (cargar, compartir, cambiar la prioridad y marcar como revisado), que se
añadieron a la matriz de src/permisos.py después de que los equipos guardaran sus roles.

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_permisos_documentos -v
"""
import copy
import unittest

from src import permisos as P

NUEVAS = ("cargar", "compartir", "prioridad", "marcar_revisado")


def estado_nuevo():
    e = {"equipo": [{"n": "Ana", "c": "ana@x", "rol": "admin"}, {"n": "Rui", "c": "rui@x", "rol": "revisor"},
                    {"n": "Pau", "c": "pau@x", "rol": "dueno_proceso"}]}
    P.migrar(e)
    return e


class Matriz(unittest.TestCase):
    def test_las_cuatro_acciones_estan_en_revisiones(self):
        for a in NUEVAS:
            self.assertIn(a, P.ACCIONES["revisiones"])

    def test_roles_iniciales(self):
        e = estado_nuevo()
        for a in NUEVAS:
            self.assertTrue(P.puede(e, "Ana", "revisiones", a), f"Admin: {a}")
            self.assertTrue(P.puede(e, "Rui", "revisiones", a), f"Revisor: {a}")
            self.assertFalse(P.puede(e, "Pau", "revisiones", a), f"Dueño de Proceso: {a}")

    def test_exigir_da_un_mensaje_legible(self):
        e = estado_nuevo()
        with self.assertRaises(P.Denegado) as cm:
            P.exigir(e, "Pau", "revisiones", "cargar")
        self.assertIn("Cargar documentos", str(cm.exception))


class RolesGuardadosAntes(unittest.TestCase):
    """Un servidor con roles guardados ANTES de que existieran estas acciones (como el de Sergio)."""

    def estado_antiguo(self):
        e = estado_nuevo()
        for r in e["roles"]:                              # quitar las acciones nuevas, como si no existieran
            for a in NUEVAS:
                r["permisos"]["revisiones"].pop(a)
        e["roles"].append({"id": "lector", "nombre": "Lector", "sistema": False, "descripcion": "",
                           "permisos": {"revisiones": {"consultar": True}, "configuracion": {}, "historico": {}}})
        e["equipo"].append({"n": "Leo", "c": "leo@x", "rol": "lector"})
        return e

    def test_quien_ya_revisa_las_tiene(self):
        e = self.estado_antiguo()
        P.migrar(e)
        for a in NUEVAS:
            self.assertTrue(P.puede(e, "Rui", "revisiones", a), f"Revisor (aprobaba y rechazaba): {a}")

    def test_quien_no_revisa_no_las_tiene(self):
        e = self.estado_antiguo()
        P.migrar(e)
        for a in NUEVAS:
            self.assertFalse(P.puede(e, "Leo", "revisiones", a), f"Lector (solo consultaba): {a}")
            self.assertFalse(P.puede(e, "Pau", "revisiones", a), f"Dueño de Proceso: {a}")

    def test_lo_que_el_admin_desactivo_sigue_desactivado(self):
        e = estado_nuevo()
        rev = next(r for r in e["roles"] if r["id"] == "revisor")
        rev["permisos"]["revisiones"]["compartir"] = False   # el Admin lo quitó a propósito
        P.migrar(e)
        self.assertFalse(P.puede(e, "Rui", "revisiones", "compartir"))

    def test_migrar_dos_veces_no_cambia_nada(self):
        e = self.estado_antiguo()
        P.migrar(e)
        antes = copy.deepcopy(e["roles"])
        P.migrar(e)
        self.assertEqual(antes, e["roles"])


if __name__ == "__main__":
    unittest.main()
