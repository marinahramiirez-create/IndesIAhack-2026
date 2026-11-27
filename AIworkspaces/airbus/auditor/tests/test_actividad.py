"""
Pruebas del registro de actividad: la cadena de huellas (src/actividad.py) y lo que anota servidor.py de cada
operación, contra el servidor de verdad en un puerto libre y con datos temporales (no tocan salidas/).

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_actividad -v
"""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import servidor
from src import actividad as AC
from src import permisos as P

D = {"docs": {"A": {"familia": "Especificaciones", "titulo": "Doc A", "version": "1.0"},
              "B": {"familia": "Registros", "titulo": "Doc B", "version": "2.0"}},
     "res": [{"documento": "A", "ubicacion": f"R{i}", "tipo": "No cumple", "clausula": "IS.I.OR.200", "conf": 0.8,
              "origen": "regla R1", "pagina": 1, "justificacion": "j"} for i in range(1, 4)]}
EQUIPO = [{"n": "Sergio", "c": "sergio@airbus.es", "rol": "admin"}, {"n": "Marina", "c": "marina@airbus.es", "rol": "aprobador"},
          {"n": "Nelson", "c": "nelson@airbus.es", "rol": "revisor"}, {"n": "Valentina", "c": "valentina@airbus.es", "rol": "dueno_proceso"}]


class Cadena(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / "actividad.jsonl"
        self.r = AC.Registro(self.ruta)
        for i in range(5):
            self.r.anotar("Marina", {"tipo": "documentos", "accion": "prioridad", "doc": f"D{i}",
                                     "detalle": {"antes": "Media", "despues": "Alta"}}, f"2026-11-27T10:0{i}:00")

    def tearDown(self):
        self.tmp.cleanup()

    def lineas(self):
        return self.ruta.read_text(encoding="utf-8").splitlines()

    def escribir(self, ls):
        self.ruta.write_text("\n".join(ls) + "\n", encoding="utf-8")

    def test_integra_y_se_recupera_al_reabrir(self):
        self.assertEqual(self.r.verificar(), {"ok": True, "total": 5, "linea": None, "motivo": ""})
        r2 = AC.Registro(self.ruta)
        self.assertEqual(len(r2.entradas), 5)
        r2.anotar("Sergio", {"tipo": "seguridad", "accion": "entrar"}, "2026-11-27T11:00:00")
        self.assertEqual(r2.verificar()["total"], 6)

    def test_detecta_un_cambio(self):
        ls = self.lineas()
        e = json.loads(ls[2])
        e["user"] = "Nelson"                        # alguien cambia quién lo hizo
        ls[2] = json.dumps(e, ensure_ascii=False)
        self.escribir(ls)
        v = self.r.verificar()
        self.assertEqual((v["ok"], v["linea"]), (False, 3))
        self.assertIn("modificado", v["motivo"])

    def test_detecta_un_cambio_aunque_rehagan_la_huella(self):
        ls = self.lineas()
        e = json.loads(ls[1])
        e["detalle"]["despues"] = "Baja"
        e["huella"] = AC._huella(e)                 # rehace la huella de esa línea, pero la siguiente ya no encaja
        ls[1] = json.dumps(e, ensure_ascii=False)
        self.escribir(ls)
        v = self.r.verificar()
        self.assertEqual((v["ok"], v["linea"]), (False, 3))

    def test_detecta_una_linea_borrada(self):
        ls = self.lineas()
        self.escribir(ls[:2] + ls[3:])
        v = self.r.verificar()
        self.assertEqual((v["ok"], v["linea"]), (False, 3))

    def test_detecta_una_linea_ilegible(self):
        ls = self.lineas()
        ls[4] = "{roto"
        self.escribir(ls)
        self.assertEqual(self.r.verificar()["linea"], 5)

    def test_filtros_y_csv(self):
        self.r.anotar("Sergio", {"tipo": "seguridad", "accion": "entrar"}, "2026-11-28T09:00:00")
        e = self.r.entradas
        self.assertEqual(AC.filtrar(e, {})[0]["user"], "Sergio")          # lo más reciente primero
        self.assertEqual(len(AC.filtrar(e, {"persona": "Marina"})), 5)
        self.assertEqual(len(AC.filtrar(e, {"tipo": "seguridad"})), 1)
        self.assertEqual(len(AC.filtrar(e, {"doc": "D3"})), 1)
        self.assertEqual(len(AC.filtrar(e, {"desde": "2026-11-28"})), 1)
        self.assertEqual(len(AC.filtrar(e, {"hasta": "2026-11-27"})), 5)
        self.assertEqual(len(AC.filtrar(e, {"q": "prioridad de d2"})), 1)
        p = AC.pagina(AC.filtrar(e, {}), 2, 4)
        self.assertEqual((p["total"], p["paginas"], len(p["datos"])), (6, 2, 2))
        txt = AC.a_csv(AC.filtrar(e, {}))
        self.assertTrue(txt.startswith("﻿n;fecha;persona;tipo"))
        self.assertIn("Cambió la prioridad de D0: Media → Alta", txt)


class EnElServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raiz = Path(cls.tmp.name)
        web = raiz / "revision"
        web.mkdir()
        (web / "index.html").write_text(f"<script>\nconst D={json.dumps(D)};\n</script>", encoding="utf-8")
        cls.antes = {k: getattr(servidor, k) for k in ("WEB", "DATOS", "VERSIONES", "ADJUNTOS")}
        servidor.WEB, servidor.DATOS = web, raiz / "colaboracion.json"
        servidor.VERSIONES, servidor.ADJUNTOS = raiz / "versiones", raiz / "adjuntos"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        cls.puerto = cls.srv.server_address[1]
        servidor._HOSTS.clear()
        servidor._HOSTS.update(servidor._hosts_permitidos(cls.puerto, False, []))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        servidor._HOSTS.clear()
        for k, v in cls.antes.items():
            setattr(servidor, k, v)
        servidor._registro[0] = None
        cls.tmp.cleanup()

    def setUp(self):
        e = {"seq": 0, "dec": {}, "comentarios": [], "avisos": [], "mensajes": [], "equipo": [dict(m) for m in EQUIPO],
             "chats": [{"id": "general", "tipo": "canal", "nombre": "general", "autor": "", "miembros": {}}],
             "n_grupos": 0, "adjuntos": {}, "ediciones": {}, "versiones": {}, "docs_meta": {}, "compartidos": [], "cargados": {},
             "config": {"plazo_dias": 15, "inicio": "2026-11-10"}}
        P.migrar(e)
        servidor._estado = e
        servidor._tokens.clear()
        servidor.DATOS.with_name("actividad.jsonl").unlink(missing_ok=True)
        servidor._registro[0] = None
        servidor._cargar_documentos()
        self.tk = {}

    # --- utilidades
    def pedir(self, metodo, ruta, cuerpo=None, token=None):
        c = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        cab = {"Host": f"localhost:{self.puerto}"}
        if cuerpo is not None:
            cab["Content-Type"] = "application/json"
        if token:
            cab["X-Sesion"] = token
        c.request(metodo, ruta, json.dumps(cuerpo).encode() if cuerpo is not None else None, cab)
        r = c.getresponse()
        b = r.read()
        c.close()
        return r.status, b

    def token(self, quien):
        if quien not in self.tk:
            _, b = self.pedir("POST", "/api/login", {"correo": f"{quien.lower()}@airbus.es"})
            self.tk[quien] = json.loads(b)["token"]
        return self.tk[quien]

    def op(self, quien, ruta, datos, esperado=200):
        code, b = self.pedir("POST", ruta, datos, self.token(quien))
        self.assertEqual(code, esperado, b)
        return json.loads(b)

    def registro(self, quien="Sergio", **q):
        from urllib.parse import urlencode
        code, b = self.pedir("GET", "/api/actividad?" + urlencode(q), token=self.token(quien))
        self.assertEqual(code, 200, b)
        return json.loads(b)

    def acciones(self):
        return [e["accion"] for e in servidor._reg().entradas]

    # --- pruebas
    def test_entrar_y_salir(self):
        self.token("Marina")
        self.op("Marina", "/api/sesion/cerrar", {"sid": "x"})
        self.assertEqual(self.acciones(), ["entrar", "salir"])
        self.assertEqual(servidor._reg().entradas[0]["user"], "Marina")

    def test_decisiones_ediciones_y_lo_que_no_se_anota(self):
        self.op("Marina", "/api/decision", {"dec": "approved", "keys": ["A|R1", "A|R2"]})
        self.op("Marina", "/api/decision", {"dec": "rejected", "keys": ["A|R1"]})
        self.op("Marina", "/api/deshacer", {"key": "A|R1"})
        self.op("Marina", "/api/comentario", {"key": "A|R2", "texto": "texto privado del debate"})
        self.op("Marina", "/api/edicion", {"key": "A|R3", "tipo": "Observación", "clausula": "IS.I.OR.200", "justificacion": "j"})
        self.op("Marina", "/api/mensaje", {"chat": "general", "texto": "hola equipo"})
        self.op("Nelson", "/api/decision", {"dec": "approved", "keys": ["X|R9"]}, 400)     # fallida: no se anota
        self.assertEqual(self.acciones(), ["entrar", "decidir", "decidir", "deshacer", "comentar", "editar_hallazgo", "entrar"])
        e = servidor._reg().entradas
        self.assertEqual(e[1]["detalle"]["hallazgos"], ["R1", "R2"])
        self.assertEqual(e[2]["detalle"]["antes"], ["aceptado"])
        self.assertEqual(e[5]["detalle"], {"antes": {"tipo": "No cumple"}, "despues": {"tipo": "Observación"}})
        todo = servidor.DATOS.with_name("actividad.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("texto privado", todo)                # ni comentarios ni chat
        self.assertNotIn("hola equipo", todo)

    def test_documentos_y_escalados(self):
        self.op("Marina", "/api/doc/prioridad", {"doc": "A", "prioridad": "Alta"})
        self.op("Marina", "/api/compartir", {"doc": "A", "para": ["Nelson"], "nota": "míralo"})
        self.op("Marina", "/api/escalar", {"doc": "A", "para": "Valentina", "nota": ""})
        self.op("Marina", "/api/escalar/quitar", {"doc": "A"})
        r = self.registro(doc="A")
        self.assertEqual([x["texto"] for x in r["datos"]],
                         ["Quitó el escalamiento de A (era de Valentina)", "Escaló A a Valentina",
                          "Compartió A con Nelson", "Cambió la prioridad de A: Media → Alta"])

    def test_configuracion_con_antes_y_despues(self):
        self.op("Sergio", "/api/equipo/alta", {"n": "Ana", "c": "ana@airbus.es", "rol": "revisor"})
        self.op("Sergio", "/api/equipo/editar", {"n": "Ana", "rol": "aprobador"})
        self.op("Sergio", "/api/config/plazo", {"plazo_dias": 20})
        rol = next(r for r in servidor._estado["roles"] if r["id"] == "revisor")
        perm = json.loads(json.dumps(rol["permisos"]))
        perm["revisiones"]["comentar"] = False
        self.op("Sergio", "/api/rol/editar", {"id": "revisor", "permisos": perm})
        self.op("Sergio", "/api/equipo/baja", {"n": "Ana"})
        e = {x["accion"]: x for x in servidor._reg().entradas}
        self.assertEqual(e["editar_usuario"]["detalle"], {"antes": {"rol": "revisor"}, "despues": {"rol": "aprobador"}})
        self.assertEqual(e["plazo"]["detalle"], {"antes": {"plazo_dias": 15}, "despues": {"plazo_dias": 20}})
        self.assertEqual(e["editar_rol"]["detalle"]["despues"], {"revisiones.comentar": False})
        self.assertIn("revisiones.comentar: sí → no", self.registro(tipo="configuracion")["datos"][1]["cambios"])
        self.assertEqual(e["baja_usuario"]["detalle"]["antes"]["c"], "ana@airbus.es")

    def test_claves_de_api(self):
        r = self.op("Marina", "/api/claves/crear", {"nombre": "Power BI", "dias": 90, "alcances": ["metricas"]})
        self.op("Sergio", "/api/claves/revocar", {"id": r["registro"]["id"]})
        txt = servidor.DATOS.with_name("actividad.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(r["clave"], txt)                      # la clave en claro tampoco va al registro
        textos = [x["texto"] for x in self.registro(tipo="seguridad")["datos"]]
        self.assertIn("Revocó la clave de API Power BI (" + r["registro"]["prefijo"] + "…) de Marina", textos)

    def test_quien_ve_que(self):
        self.op("Marina", "/api/doc/prioridad", {"doc": "A", "prioridad": "Alta"})
        self.op("Nelson", "/api/decision", {"dec": "approved", "keys": ["A|R1"]})
        r = self.registro("Marina")
        self.assertTrue(r["todo"])
        self.assertEqual(r["personas"], ["Marina", "Nelson", "Sergio"] if "Sergio" in self.tk else ["Marina", "Nelson"])
        r = self.registro("Nelson", persona="Marina")          # el Revisor solo ve lo suyo, pida lo que pida
        self.assertFalse(r["todo"])
        self.assertEqual({x["user"] for x in r["datos"]}, {"Nelson"})
        self.assertEqual(self.pedir("GET", "/api/actividad/integridad", token=self.token("Nelson"))[0], 403)
        self.assertEqual(self.pedir("GET", "/api/actividad", token="falso")[0], 401)

    def test_integridad_y_csv(self):
        self.op("Marina", "/api/doc/prioridad", {"doc": "A", "prioridad": "Alta"})
        code, b = self.pedir("GET", "/api/actividad/integridad", token=self.token("Marina"))
        self.assertEqual(json.loads(b), {"ok": True, "total": 2, "linea": None, "motivo": ""})
        f = servidor.DATOS.with_name("actividad.jsonl")
        f.write_text(f.read_text(encoding="utf-8").replace('"Alta"', '"Baja"'), encoding="utf-8")
        code, b = self.pedir("GET", "/api/actividad/integridad", token=self.token("Marina"))
        self.assertEqual((json.loads(b)["ok"], json.loads(b)["linea"]), (False, 2))
        code, b = self.pedir("GET", "/api/actividad/csv?tipo=documentos", token=self.token("Marina"))
        self.assertEqual(code, 200)
        self.assertEqual(len(b.decode("utf-8").strip().splitlines()), 2)

    def test_no_se_puede_borrar_ni_editar(self):
        for ruta in ("/api/actividad", "/api/actividad/borrar", "/api/actividad/editar"):
            self.assertEqual(self.op("Sergio", ruta, {"n": 1}, 404)["error"], "ruta desconocida")


class Permiso(unittest.TestCase):
    def test_roles(self):
        e = {"equipo": [dict(m) for m in EQUIPO]}
        P.migrar(e)
        for r in e["roles"]:
            r["permisos"].pop("actividad", None)        # roles guardados antes de existir el registro
        P.migrar(e)
        self.assertEqual({m["n"]: P.puede(e, m["n"], "actividad", "consultar") for m in EQUIPO},
                         {"Sergio": True, "Marina": True, "Nelson": False, "Valentina": False})


if __name__ == "__main__":
    unittest.main()
