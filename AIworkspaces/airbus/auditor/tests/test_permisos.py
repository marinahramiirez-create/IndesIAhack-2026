"""
Pruebas de usuarios, roles, permisos y escalamiento (src/permisos.py + servidor.py).

Las de servidor levantan servidor.py de verdad en un puerto libre, con datos temporales (no tocan salidas/), y
hacen peticiones HTTP como lo haría alguien que se salta la interfaz: así se comprueba que la autorización está
en el backend y no solo en los botones.

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_permisos -v
                                 (Windows: .\\.venv\\Scripts\\python -m unittest tests.test_permisos -v)
"""
import copy
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import servidor
from src import permisos as P

# Pantalla mínima: DOC-A con 2 hallazgos, DOC-B con 1, DOC-C sin hallazgos
DATOS_PAGINA = {"docs": {"DOC-A": {}, "DOC-B": {}, "DOC-C": {}},
                "res": [{"documento": "DOC-A", "ubicacion": "R1"}, {"documento": "DOC-A", "ubicacion": "R2"},
                        {"documento": "DOC-B", "ubicacion": "R1"}]}
ESTADO_INICIAL = copy.deepcopy(servidor._estado)


def estado_nuevo() -> dict:
    e = copy.deepcopy(ESTADO_INICIAL)
    P.migrar(e)
    return e


# ====================================================================== lógica pura
class TestRoles(unittest.TestCase):
    def setUp(self):
        self.e = estado_nuevo()

    def test_crud_de_roles_por_admin(self):
        rid = P.crear_rol(self.e, "Sergio", {"nombre": "Auditor externo", "descripcion": "Solo mira",
                                             "permisos": {"revisiones": {"consultar": True}}})
        r = next(x for x in self.e["roles"] if x["id"] == rid)
        self.assertTrue(r["permisos"]["revisiones"]["consultar"])
        self.assertFalse(r["permisos"]["revisiones"]["aprobar"])
        P.editar_rol(self.e, "Sergio", {"id": rid, "nombre": "Auditor", "permisos": {"historico": {"descargar_respuestas": True}}})
        self.assertEqual(r["nombre"], "Auditor")
        self.assertTrue(r["permisos"]["historico"]["descargar_respuestas"])
        self.assertFalse(r["permisos"]["revisiones"]["consultar"])      # la matriz se sustituye entera
        P.borrar_rol(self.e, "Sergio", rid)
        self.assertNotIn(rid, [x["id"] for x in self.e["roles"]])

    def test_solo_admin_crea_edita_y_borra_roles(self):
        for quien in ("Marina", "Nelson"):                              # Aprobador y Revisor
            with self.assertRaises(P.Denegado) as c:
                P.crear_rol(self.e, quien, {"nombre": "Otro"})
            self.assertEqual(c.exception.code, 403)
            with self.assertRaises(P.Denegado):
                P.editar_rol(self.e, quien, {"id": "revisor", "nombre": "X"})
            with self.assertRaises(P.Denegado):
                P.borrar_rol(self.e, quien, "aprobador")

    def test_ningun_permiso_concede_administrar_roles(self):
        """Aunque un rol tenga TODAS las casillas, sigue sin poder tocar roles."""
        todo = {m: {a: True for a in acc} for m, acc in P.ACCIONES.items()}
        P.editar_rol(self.e, "Sergio", {"id": "revisor", "permisos": todo})
        with self.assertRaises(P.Denegado):
            P.crear_rol(self.e, "Nelson", {"nombre": "Colado"})
        self.assertFalse(P.permisos_de(self.e, "Nelson")["admin_roles"])
        self.assertFalse(P.puede(self.e, "Nelson", "revisiones", "editar_escalados"))  # solo Dueño de Proceso

    def test_no_se_borra_un_rol_con_usuarios_ni_de_sistema(self):
        with self.assertRaises(P.Denegado) as c:
            P.borrar_rol(self.e, "Sergio", "revisor")
        self.assertIn("Nelson", str(c.exception))
        for rid in P.ROLES_SISTEMA:
            with self.assertRaises(P.Denegado):
                P.borrar_rol(self.e, "Sergio", rid)

    def test_rol_admin_inmutable_y_permisos_desconocidos_ignorados(self):
        with self.assertRaises(P.Denegado):
            P.editar_rol(self.e, "Sergio", {"id": P.ADMIN, "permisos": {}})
        rid = P.crear_rol(self.e, "Sergio", {"nombre": "Raro", "permisos": {"revisiones": {"borrar_todo": True, "aprobar": "sí"}}})
        r = next(x for x in self.e["roles"] if x["id"] == rid)
        self.assertNotIn("borrar_todo", r["permisos"]["revisiones"])
        self.assertFalse(r["permisos"]["revisiones"]["aprobar"])        # solo vale True booleano

    def test_migracion_de_roles_antiguos(self):
        e = copy.deepcopy(ESTADO_INICIAL)
        e["equipo"] = [{"n": "A", "c": "a@x.es", "rol": "Administrador"}, {"n": "B", "c": "b@x.es", "rol": "Aprobador"},
                       {"n": "C", "c": "c@x.es", "rol": "Inventado"}]
        e.pop("roles", None)
        P.migrar(e)
        self.assertEqual([m["rol"] for m in e["equipo"]], [P.ADMIN, "aprobador", "revisor"])


class TestUsuarios(unittest.TestCase):
    def setUp(self):
        self.e = estado_nuevo()

    def test_crud_de_usuarios(self):
        P.crear_usuario(self.e, "Sergio", {"n": "Lucía", "c": "lucia@airbus.es", "rol": P.DUENO})
        self.assertEqual(P.miembro(self.e, "Lucía")["rol"], P.DUENO)
        P.editar_usuario(self.e, "Sergio", {"n": "Lucía", "c": "lucia.p@airbus.es", "rol": "revisor"})
        self.assertEqual(P.miembro(self.e, "Lucía"), {"n": "Lucía", "c": "lucia.p@airbus.es", "rol": "revisor"})
        P.borrar_usuario(self.e, "Sergio", "Lucía", "2026-11-26T20:00:00")
        self.assertIsNone(P.miembro(self.e, "Lucía"))

    def test_sin_roles_no_se_crean_usuarios(self):
        """En la práctica Admin siempre existe (es de sistema); la regla se comprueba igualmente."""
        self.e["roles"] = []
        with self.assertRaises(P.Denegado) as c:
            P._comprobar_rol_asignable(self.e, "Sergio", "revisor")
        self.assertIn("no hay roles", str(c.exception))
        with self.assertRaises(P.Denegado):                               # y sin roles nadie tiene permisos
            P.crear_usuario(self.e, "Sergio", {"n": "Z", "c": "z@x.es", "rol": "revisor"})

    def test_rol_obligatorio_y_existente(self):
        with self.assertRaises(P.Denegado) as c:
            P.crear_usuario(self.e, "Sergio", {"n": "Z", "c": "z@x.es"})
        self.assertIn("necesita un rol", str(c.exception))
        with self.assertRaises(P.Denegado) as c:
            P.crear_usuario(self.e, "Sergio", {"n": "Z", "c": "z@x.es", "rol": "fantasma"})
        self.assertIn("no existe", str(c.exception))
        with self.assertRaises(P.Denegado):
            P.editar_usuario(self.e, "Sergio", {"n": "Nelson", "rol": "fantasma"})
        self.assertEqual(P.miembro(self.e, "Nelson")["rol"], "revisor")

    def test_sin_permiso_no_gestiona_usuarios(self):
        with self.assertRaises(P.Denegado):
            P.crear_usuario(self.e, "Nelson", {"n": "Z", "c": "z@x.es", "rol": "revisor"})

    def test_gestor_no_admin_no_toca_el_rol_admin(self):
        rid = P.crear_rol(self.e, "Sergio", {"nombre": "RRHH", "permisos": {"configuracion": {"gestionar_usuarios": True}}})
        P.editar_usuario(self.e, "Sergio", {"n": "Marina", "rol": rid})
        with self.assertRaises(P.Denegado):                               # no puede hacerse Admin a sí misma ni a otro
            P.editar_usuario(self.e, "Marina", {"n": "Nelson", "rol": P.ADMIN})
        with self.assertRaises(P.Denegado):
            P.crear_usuario(self.e, "Marina", {"n": "Z", "c": "z@x.es", "rol": P.ADMIN})
        with self.assertRaises(P.Denegado):                               # ni degradar o borrar a un Admin
            P.editar_usuario(self.e, "Marina", {"n": "Sergio", "rol": "revisor"})
        with self.assertRaises(P.Denegado):
            P.borrar_usuario(self.e, "Marina", "Sergio", "f")
        with self.assertRaises(P.Denegado):                               # ni cambiarse su propio rol
            P.editar_usuario(self.e, "Marina", {"n": "Marina", "rol": "revisor"})
        P.editar_usuario(self.e, "Marina", {"n": "Nelson", "rol": "aprobador"})   # lo demás, sí
        self.assertEqual(P.miembro(self.e, "Nelson")["rol"], "aprobador")

    def test_queda_al_menos_un_admin(self):
        with self.assertRaises(P.Denegado):
            P.editar_usuario(self.e, "Sergio", {"n": "Sergio", "rol": "revisor"})

    def test_edicion_fallida_no_cambia_nada(self):
        with self.assertRaises(P.Denegado):
            P.editar_usuario(self.e, "Sergio", {"n": "Nelson", "c": "nuevo@x.es", "rol": "fantasma"})
        self.assertEqual(P.miembro(self.e, "Nelson")["c"], "nelson@airbus.es")

    def test_cambio_de_rol_cambia_permisos_efectivos(self):
        self.assertTrue(P.puede(self.e, "Nelson", "revisiones", "aprobar"))
        P.editar_usuario(self.e, "Sergio", {"n": "Nelson", "rol": P.DUENO})
        self.assertFalse(P.puede(self.e, "Nelson", "revisiones", "aprobar"))
        self.assertTrue(P.puede(self.e, "Nelson", "revisiones", "editar_escalados"))

    def test_sin_usuario_no_hay_permisos(self):
        self.assertFalse(P.puede(self.e, "Desconocido", "revisiones", "consultar"))
        self.assertFalse(P.puede(self.e, "", "revisiones", "consultar"))


class TestEscalamiento(unittest.TestCase):
    HALL = ["DOC-A|R1", "DOC-A|R2"]

    def setUp(self):
        self.e = estado_nuevo()
        P.crear_usuario(self.e, "Sergio", {"n": "Lucía", "c": "lucia@x.es", "rol": P.DUENO})
        P.crear_usuario(self.e, "Sergio", {"n": "Pablo", "c": "pablo@x.es", "rol": P.DUENO})

    def motivo(self, user):
        return P.motivo_no_editar(self.e, user, "DOC-A", self.HALL)

    def test_sin_escalamiento_nadie_edita(self):
        for u in ("Lucía", "Sergio", "Nelson"):
            self.assertIn("no está escalado", self.motivo(u))

    def test_solo_edita_el_dueno_al_que_se_escalo(self):
        P.escalar(self.e, "Nelson", "DOC-A", "Lucía", "corrige R1", "f", {"DOC-A"})
        self.assertIsNone(self.motivo("Lucía"))
        self.assertIn("escalado a Lucía", self.motivo("Pablo"))           # mismo rol, otra persona
        self.assertIn("escalado a Lucía", self.motivo("Sergio"))          # ni el Admin

    def test_solo_se_escala_a_un_dueno_de_proceso(self):
        with self.assertRaises(P.Denegado):
            P.escalar(self.e, "Nelson", "DOC-A", "Marina", "", "f", {"DOC-A"})
        with self.assertRaises(P.Denegado):
            P.escalar(self.e, "Nelson", "NO-EXISTE", "Lucía", "", "f", {"DOC-A"})

    def test_escalar_exige_permiso(self):
        with self.assertRaises(P.Denegado):
            P.escalar(self.e, "Lucía", "DOC-A", "Pablo", "", "f", {"DOC-A"})   # Dueño de Proceso no escala

    def test_cambio_de_destinatario(self):
        P.escalar(self.e, "Nelson", "DOC-A", "Lucía", "", "f", {"DOC-A"})
        self.assertEqual(P.escalar(self.e, "Nelson", "DOC-A", "Pablo", "", "f", {"DOC-A"}), "cambiar")
        self.assertIsNone(self.motivo("Pablo"))
        self.assertIsNotNone(self.motivo("Lucía"))
        self.assertEqual([h["accion"] for h in self.e["escalados_hist"]], ["escalar", "cambiar"])

    def test_destinatario_que_cambia_de_rol_pierde_la_edicion(self):
        P.escalar(self.e, "Nelson", "DOC-A", "Lucía", "", "f", {"DOC-A"})
        P.editar_usuario(self.e, "Sergio", {"n": "Lucía", "rol": "revisor"})
        self.assertIn("Dueño de Proceso", self.motivo("Lucía"))

    def test_permiso_editar_escalados_desactivado(self):
        P.escalar(self.e, "Nelson", "DOC-A", "Lucía", "", "f", {"DOC-A"})
        perm = copy.deepcopy(next(r for r in self.e["roles"] if r["id"] == P.DUENO)["permisos"])
        perm["revisiones"]["editar_escalados"] = False
        P.editar_rol(self.e, "Sergio", {"id": P.DUENO, "permisos": perm})
        self.assertIn("Editar documentos escalados", self.motivo("Lucía"))

    def test_documento_completado_no_se_edita(self):
        P.escalar(self.e, "Nelson", "DOC-A", "Lucía", "", "f", {"DOC-A"})
        self.e["dec"] = {"DOC-A|R1": {"dec": "approved"}}
        self.assertIsNone(self.motivo("Lucía"))                           # En revisión: sí
        self.e["dec"]["DOC-A|R2"] = {"dec": "rejected"}
        self.assertIn("Completado", self.motivo("Lucía"))                 # Completado: no

    def test_quitar_escalamiento_y_borrar_destinatario(self):
        P.escalar(self.e, "Nelson", "DOC-A", "Lucía", "", "f", {"DOC-A"})
        with self.assertRaises(P.Denegado):
            P.quitar_escalado(self.e, "Pablo", "DOC-A", "f")              # ni puede escalar ni es el destinatario
        P.quitar_escalado(self.e, "Lucía", "DOC-A", "f")                  # el destinatario sí (al terminar)
        self.assertNotIn("DOC-A", self.e["escalados"])
        P.escalar(self.e, "Nelson", "DOC-A", "Pablo", "", "f", {"DOC-A"})
        self.assertEqual(P.borrar_usuario(self.e, "Sergio", "Pablo", "f"), ["DOC-A"])
        self.assertNotIn("DOC-A", self.e["escalados"])


# ====================================================================== servidor HTTP de verdad
class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raiz = Path(cls.tmp.name)
        web = raiz / "revision"
        web.mkdir()
        (web / "index.html").write_text("<script>\nconst D=" + json.dumps(DATOS_PAGINA) + ";\n</script>", encoding="utf-8")
        cls.antes = {k: getattr(servidor, k) for k in ("WEB", "DATOS", "VERSIONES", "ADJUNTOS")}
        servidor.WEB, servidor.DATOS = web, raiz / "colaboracion.json"
        servidor.VERSIONES, servidor.ADJUNTOS = raiz / "versiones", raiz / "adjuntos"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for k, v in cls.antes.items():
            setattr(servidor, k, v)
        cls.tmp.cleanup()

    def setUp(self):
        servidor._estado = estado_nuevo()
        servidor._tokens.clear()
        servidor._cargar_documentos()
        self.tk = {}

    # --- utilidades
    def pedir(self, ruta, datos=None, token=None, metodo="POST"):
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Sesion"] = token
        req = Request(self.url + ruta, data=json.dumps(datos or {}).encode() if metodo == "POST" else None,
                      headers=h, method=metodo)
        try:
            with urlopen(req) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def entrar(self, correo):
        code, j = self.pedir("/api/login", {"correo": correo})
        self.assertEqual(code, 200, j)
        return j["token"]

    def como(self, nombre):
        if nombre not in self.tk:
            self.tk[nombre] = self.entrar(P.miembro(servidor._estado, nombre)["c"])
        return self.tk[nombre]

    def post(self, quien, ruta, datos=None):
        return self.pedir(ruta, datos, self.como(quien))

    def preparar_duenos(self):
        for n in ("Lucía", "Pablo"):
            code, j = self.post("Sergio", "/api/equipo/alta", {"n": n, "c": f"{n.lower()}@x.es", "rol": P.DUENO})
            self.assertEqual(code, 200, j)

    # --- autenticación
    def test_sin_sesion_todo_401(self):
        for ruta in ("/api/decision", "/api/rol/crear", "/api/equipo/alta", "/api/escalar", "/api/version/guardar"):
            code, _ = self.pedir(ruta, {"user": "Sergio"})                 # el campo «user» del cuerpo no sirve
            self.assertEqual(code, 401, ruta)
        self.assertEqual(self.pedir("/api/estado", metodo="GET")[0], 401)
        self.assertEqual(self.pedir("/api/decision", {"keys": ["DOC-A|R1"], "dec": "approved"}, token="falso")[0], 401)

    def test_login_solo_para_dados_de_alta(self):
        self.assertEqual(self.pedir("/api/login", {"correo": "intruso@x.es"})[0], 403)

    def test_suplantar_con_el_cuerpo_no_funciona(self):
        """Nelson (Revisor) manda user=Sergio para crear un rol: el servidor usa el token, no el cuerpo."""
        code, _ = self.post("Nelson", "/api/rol/crear", {"user": "Sergio", "nombre": "Colado"})
        self.assertEqual(code, 403)

    def test_usuario_eliminado_pierde_la_sesion(self):
        tk = self.como("Nelson")
        self.assertEqual(self.post("Sergio", "/api/equipo/baja", {"n": "Nelson"})[0], 200)
        self.assertEqual(self.pedir("/api/estado", token=tk, metodo="GET")[0], 401)

    # --- roles por HTTP
    def test_roles_solo_admin_por_http(self):
        code, j = self.post("Sergio", "/api/rol/crear", {"nombre": "Lector", "permisos": {"revisiones": {"consultar": True}}})
        self.assertEqual(code, 200, j)
        for ruta, datos in (("/api/rol/crear", {"nombre": "X"}), ("/api/rol/editar", {"id": j["id"], "nombre": "Y"}),
                            ("/api/rol/borrar", {"id": j["id"]})):
            self.assertEqual(self.post("Marina", ruta, datos)[0], 403, ruta)
        _, est = self.pedir("/api/estado", token=self.como("Marina"), metodo="GET")    # pero los ve
        self.assertIn("Lector", [r["nombre"] for r in est["roles"]])
        self.assertFalse(est["permisos"]["admin_roles"])

    def test_borrar_rol_con_usuarios_por_http(self):
        code, j = self.post("Sergio", "/api/rol/borrar", {"id": "revisor"})
        self.assertEqual(code, 400)
        self.assertIn("usuario", j["error"])

    # --- aprobar / rechazar independientes
    def test_aprobar_y_rechazar_independientes(self):
        rid = self.post("Sergio", "/api/rol/crear", {"nombre": "Solo aprueba",
                        "permisos": {"revisiones": {"consultar": True, "aprobar": True}}})[1]["id"]
        self.post("Sergio", "/api/equipo/editar", {"n": "Nelson", "rol": rid})
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "approved"})[0], 200)
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R2"], "dec": "rejected"})[0], 403)
        # y cambiar a «rechazado» algo ya aprobado tampoco (sería rechazar)
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "rejected"})[0], 403)
        self.assertEqual(servidor._estado["dec"]["DOC-A|R1"]["dec"], "approved")

    def test_consultar_no_implica_decidir(self):
        self.preparar_duenos()                                             # Dueño de Proceso consulta, no decide
        self.assertEqual(self.post("Lucía", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "approved"})[0], 403)
        self.assertEqual(self.post("Lucía", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "rejected"})[0], 403)
        self.assertNotIn("DOC-A|R1", servidor._estado["dec"])

    def test_decision_no_valida_o_hallazgo_inventado(self):
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "lo_que_sea"})[0], 400)
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-Z|R9"], "dec": "approved"})[0], 400)

    def test_deshacer_exige_el_permiso_de_esa_decision(self):
        self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "rejected"})
        rid = self.post("Sergio", "/api/rol/crear", {"nombre": "Aprueba", "permisos": {"revisiones": {"aprobar": True}}})[1]["id"]
        self.post("Sergio", "/api/equipo/editar", {"n": "Marina", "rol": rid})
        self.assertEqual(self.post("Marina", "/api/deshacer", {"key": "DOC-A|R1"})[0], 403)

    # --- edición de documentos escalados
    def guardar_version(self, quien, doc="DOC-A"):
        return self.post(quien, "/api/version/guardar", {"doc": doc, "paginas": {"1": "texto corregido"}, "nota": "prueba"})

    def test_edicion_de_documentos_escalados(self):
        self.preparar_duenos()
        code, j = self.guardar_version("Lucía")                            # sin escalar
        self.assertEqual(code, 403)
        self.assertIn("no está escalado", j["error"])
        self.assertEqual(self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Lucía"})[0], 200)
        self.assertEqual(self.guardar_version("Lucía")[0], 200)             # escalado a ella: sí
        code, j = self.guardar_version("Pablo")                            # mismo rol, otra persona: no
        self.assertEqual(code, 403)
        self.assertIn("Lucía", j["error"])
        self.assertEqual(self.guardar_version("Sergio")[0], 403)           # ni el Admin
        self.assertEqual(self.guardar_version("Lucía", "DOC-B")[0], 403)   # otro documento suyo no escalado
        self.assertEqual(len(servidor._estado["versiones"]["DOC-A"]), 1)

    def test_devuelto_bloquea_aprobar_y_rechazar_hasta_corregir(self):
        self.preparar_duenos()
        self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R2"], "dec": "rejected"})
        self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Lucía", "nota": "corrige R1"})
        for dec in ("approved", "rejected"):                                  # ni el Admin decide mientras espera
            code, j = self.post("Sergio", "/api/decision", {"keys": ["DOC-A|R1"], "dec": dec})
            self.assertEqual(code, 403)
            self.assertIn("Lucía", j["error"])
        self.assertEqual(self.post("Sergio", "/api/deshacer", {"key": "DOC-A|R2"})[0], 403)
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-B|R1"], "dec": "approved"})[0], 200)  # otro doc, sí
        self.assertEqual(self.guardar_version("Lucía")[0], 200)
        self.assertEqual(servidor._estado["escalados"]["DOC-A"]["corregido"]["version"], 1)
        self.assertTrue(any(a["para"] == "Nelson" and "guardado los cambios" in a["texto"] for a in servidor._estado["avisos"]))
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "approved"})[0], 200)
        # devolverlo a otra persona vuelve a bloquear hasta su corrección
        self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Pablo"})
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "rejected"})[0], 403)
        self.post("Nelson", "/api/escalar/quitar", {"doc": "DOC-A"})          # quitar el escalamiento desbloquea
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "rejected"})[0], 200)

    def test_editar_sin_rol_dueno_aunque_este_escalado(self):
        self.preparar_duenos()
        self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Lucía"})
        self.post("Sergio", "/api/equipo/editar", {"n": "Lucía", "rol": "revisor"})   # cambio de rol del asignado
        code, j = self.guardar_version("Lucía")
        self.assertEqual(code, 403)
        self.assertIn("Dueño de Proceso", j["error"])

    def test_escalar_a_quien_no_es_dueno(self):
        self.assertEqual(self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Marina"})[0], 400)

    def test_cambio_de_destinatario_por_http(self):
        self.preparar_duenos()
        self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Lucía"})
        code, j = self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Pablo"})
        self.assertEqual((code, j.get("accion")), (200, "cambiar"))
        self.assertEqual(self.guardar_version("Lucía")[0], 403)
        self.assertEqual(self.guardar_version("Pablo")[0], 200)
        avisos = [a for a in servidor._estado["avisos"] if a["key"] == "DOC-A|escalado"]
        self.assertEqual({a["para"] for a in avisos}, {"Lucía", "Pablo", "Nelson"})   # los dos se enteran, y quien
        #                                                                        escaló sabe que Pablo ya corrigió

    def test_documento_escalado_que_se_completa(self):
        self.preparar_duenos()
        self.post("Nelson", "/api/escalar", {"doc": "DOC-A", "para": "Lucía"})
        self.assertEqual(self.guardar_version("Lucía")[0], 200)            # corrige y desbloquea las decisiones
        self.assertEqual(self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1", "DOC-A|R2"], "dec": "approved"})[0], 200)
        code, j = self.guardar_version("Lucía")
        self.assertEqual(code, 403)
        self.assertIn("Completado", j["error"])
        _, est = self.pedir("/api/estado", token=self.como("Lucía"), metodo="GET")
        self.assertIn("Completado", est["editables"]["DOC-A"])             # la pantalla lo sabe y lo explica

    # --- configuración, consulta y estado
    def test_gestion_de_usuarios_por_http(self):
        self.assertEqual(self.post("Nelson", "/api/equipo/alta", {"n": "Z", "c": "z@x.es", "rol": "revisor"})[0], 403)
        self.assertEqual(self.post("Sergio", "/api/equipo/alta", {"n": "Z", "c": "z@x.es"})[0], 400)        # sin rol
        self.assertEqual(self.post("Sergio", "/api/equipo/alta", {"n": "Z", "c": "z@x.es", "rol": "nope"})[0], 400)
        self.assertEqual(self.post("Sergio", "/api/equipo/alta", {"n": "Z", "c": "z@x.es", "rol": "revisor"})[0], 200)
        self.assertEqual(self.post("Sergio", "/api/equipo/editar", {"n": "Z", "rol": "aprobador"})[0], 200)
        self.assertEqual(self.post("Sergio", "/api/equipo/baja", {"n": "Z"})[0], 200)

    def test_sin_consultar_no_recibe_datos_de_revision(self):
        self.post("Nelson", "/api/decision", {"keys": ["DOC-A|R1"], "dec": "approved"})
        rid = self.post("Sergio", "/api/rol/crear", {"nombre": "Nada"})[1]["id"]
        self.post("Sergio", "/api/equipo/editar", {"n": "Marina", "rol": rid})
        _, est = self.pedir("/api/estado", token=self.como("Marina"), metodo="GET")
        self.assertEqual(est["dec"], {})
        self.assertEqual(self.post("Marina", "/api/comentario", {"key": "DOC-A|R1", "texto": "hola"})[0], 403)
        self.assertEqual(self.post("Marina", "/api/edicion", {"key": "DOC-A|R1", "tipo": "No cumple", "clausula": "IS.I.OR.200",
                                                              "justificacion": "x"})[0], 403)

    def test_plazo_de_respuesta(self):
        _, est = self.pedir("/api/estado", token=self.como("Nelson"), metodo="GET")
        self.assertEqual(est["config"]["plazo_dias"], 15)                  # por defecto
        self.assertTrue(est["config"]["inicio"])
        self.assertEqual(self.post("Nelson", "/api/config/plazo", {"plazo_dias": 30})[0], 403)   # Revisor: no
        self.assertEqual(self.post("Marina", "/api/config/plazo", {"plazo_dias": 30, "inicio": "2026-11-20"})[0], 200)
        self.assertEqual(servidor._estado["config"], {"plazo_dias": 30, "inicio": "2026-11-20"})
        for malo in ({"plazo_dias": 0}, {"plazo_dias": "x"}, {"plazo_dias": 999}, {"inicio": "2026-13-45"}):
            self.assertEqual(self.post("Sergio", "/api/config/plazo", malo)[0], 400, malo)
        self.assertEqual(servidor._estado["config"]["plazo_dias"], 30)    # lo rechazado no cambia nada

    def test_permisos_persisten_en_disco(self):
        rid = self.post("Sergio", "/api/rol/crear", {"nombre": "Persistente", "permisos": {"historico": {"descargar_revision": True}}})[1]["id"]
        guardado = json.loads(servidor.DATOS.read_text(encoding="utf-8"))
        r = next(x for x in guardado["roles"] if x["id"] == rid)
        self.assertTrue(r["permisos"]["historico"]["descargar_revision"])
        servidor._estado = estado_nuevo()                                  # «reinicio»: se vuelve a cargar del disco
        servidor._cargar()
        self.assertIn(rid, [x["id"] for x in servidor._estado["roles"]])


if __name__ == "__main__":
    unittest.main()
