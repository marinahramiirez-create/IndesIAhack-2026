"""
Pruebas de la API externa (/api/v1/…) contra servidor.py de verdad, en un puerto libre y con datos temporales
(no tocan salidas/). Mismo método que tests/test_seguridad.py.

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_api_v1 -v
"""
import http.client
import json
import tempfile
import threading
import unittest
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import servidor
from src import metricas as M
from src import permisos as P

D = {"docs": {"A": {"familia": "Especificaciones", "titulo": "Doc A", "version": "1.0"},
              "B": {"familia": "Registros", "titulo": "Doc B", "version": "2.0"}},
     "res": [{"documento": "A", "ubicacion": f"R{i}", "tipo": "No cumple", "clausula": "IS.I.OR.200", "conf": 0.8,
              "origen": "regla R1", "pagina": 1, "justificacion": "j"} for i in range(1, 4)]
            + [{"documento": "B", "ubicacion": "R1", "tipo": "Inconsistencia", "clausula": "IS.I.OR.230", "conf": 0.9,
                "origen": "llm", "pagina": 2, "justificacion": "k"}]}
EQUIPO = [{"n": "Sergio", "c": "sergio@airbus.es", "rol": "admin"}, {"n": "Marina", "c": "marina@airbus.es", "rol": "aprobador"},
          {"n": "Nelson", "c": "nelson@airbus.es", "rol": "revisor"}]


class TestApiV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raiz = Path(cls.tmp.name)
        web = raiz / "revision"
        web.mkdir()
        (web / "index.html").write_text(f"<script>\nconst D={json.dumps(D)};\n</script>", encoding="utf-8")
        cls.antes = {k: getattr(servidor, k) for k in ("WEB", "DATOS", "VERSIONES", "ADJUNTOS", "API_RITMO")}
        servidor.WEB, servidor.DATOS = web, raiz / "colaboracion.json"
        servidor.VERSIONES, servidor.ADJUNTOS = raiz / "versiones", raiz / "adjuntos"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        cls.puerto = cls.srv.server_address[1]
        cls.host = f"localhost:{cls.puerto}"
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
        cls.tmp.cleanup()

    def setUp(self):
        e = {"seq": 0, "dec": {"A|R1": {"dec": "approved", "note": "", "user": "Marina", "fecha": "2026-11-20T10:00:00"},
                               "B|R1": {"dec": "rejected", "note": "", "user": "Nelson", "fecha": "2026-11-21T10:00:00"}},
             "comentarios": [], "avisos": [], "mensajes": [], "equipo": [dict(m) for m in EQUIPO],
             "chats": [{"id": "general", "tipo": "canal", "nombre": "general", "autor": "", "miembros": {}}],
             "n_grupos": 0, "adjuntos": {}, "ediciones": {}, "versiones": {}, "docs_meta": {}, "compartidos": [], "cargados": {},
             "config": {"plazo_dias": 15, "inicio": "2026-11-10"}}
        P.migrar(e)
        servidor._estado = e
        servidor._tokens.clear()
        servidor._ritmo_api.clear()
        servidor.API_RITMO = (60, 60.0)
        servidor._cargar_documentos()

    # --- utilidades
    def pedir(self, metodo, ruta, cuerpo=None, cab=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        c.putrequest(metodo, ruta, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", host or self.host)
        cab = dict(cab or {})
        if cuerpo is not None:
            cab.setdefault("Content-Length", str(len(cuerpo)))
        for k, v in cab.items():
            c.putheader(k, v)
        c.endheaders()
        if cuerpo:
            c.send(cuerpo)
        r = c.getresponse()
        datos = r.read()
        c.close()
        return r.status, dict(r.getheaders()), datos

    def entrar(self, correo):
        _, _, b = self.pedir("POST", "/api/login", json.dumps({"correo": correo}).encode(), {"Content-Type": "application/json"})
        return json.loads(b)["token"]

    def post(self, token, ruta, datos):
        code, _, b = self.pedir("POST", ruta, json.dumps(datos).encode(), {"Content-Type": "application/json", "X-Sesion": token})
        return code, json.loads(b)

    def nueva_clave(self, correo="marina@airbus.es", alcances=("metricas", "documentos", "hallazgos")):
        code, r = self.post(self.entrar(correo), "/api/claves/crear", {"nombre": "Power BI", "dias": 90, "alcances": list(alcances)})
        self.assertEqual(code, 200, r)
        return r["clave"], r["registro"]

    def api(self, ruta, clave=None, host=None):
        code, cab, b = self.pedir("GET", ruta, cab={"Authorization": f"Bearer {clave}"} if clave else None, host=host)
        return code, cab, b

    # --- pruebas
    def test_ayuda_sin_clave(self):
        code, cab, b = self.api("/api/v1/docs")
        self.assertEqual(code, 200)
        self.assertIn("text/html", cab["Content-Type"])
        self.assertIn("Authorization: Bearer", b.decode())
        code, _, b = self.api("/api/v1/openapi.json")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(b)["openapi"], "3.1.0")

    def test_sin_clave_o_falsa(self):
        for clave in (None, "nas_inventada", "otra-cosa"):
            code, _, b = self.api("/api/v1/metricas/resumen", clave)
            self.assertEqual(code, 401, clave)
            self.assertEqual(json.loads(b)["error"]["codigo"], "no_autorizado")

    def test_la_clave_no_va_en_la_direccion(self):
        clave, _ = self.nueva_clave()
        self.assertEqual(self.api(f"/api/v1/metricas/resumen?clave={clave}")[0], 401)

    def test_quien_puede_crear(self):
        code, r = self.post(self.entrar("nelson@airbus.es"), "/api/claves/crear", {"nombre": "x", "dias": 90, "alcances": ["metricas"]})
        self.assertEqual(code, 403, r)

    def test_metricas_iguales_que_la_pantalla(self):
        clave, _ = self.nueva_clave()
        code, _, b = self.api("/api/v1/metricas/resumen?familia=Especificaciones", clave)
        self.assertEqual(code, 200)
        esperado = M.calcular(D["res"], D["docs"], servidor._estado, [], {"familia": "Especificaciones"}, date.today())
        self.assertEqual(json.loads(b)["datos"], esperado["resumen"])
        self.assertEqual(self.api("/api/v1/metricas/otra", clave)[0], 404)

    def test_documentos_paginados_y_csv(self):
        clave, _ = self.nueva_clave()
        code, _, b = self.api("/api/v1/documentos?limite=1&pagina=2", clave)
        r = json.loads(b)
        self.assertEqual((code, r["total"], r["paginas"], r["pagina"], len(r["datos"])), (200, 2, 2, 2, 1))
        self.assertEqual(self.api("/api/v1/documentos?limite=0", clave)[0], 400)
        code, cab, b = self.api("/api/v1/documentos?formato=csv", clave)
        txt = b.decode("utf-8")
        self.assertEqual(code, 200)
        self.assertIn("text/csv", cab["Content-Type"])
        self.assertTrue(txt.startswith("﻿documento;titulo;familia;estado"), txt[:60])
        self.assertEqual(len(txt.strip().splitlines()), 3)

    def test_hallazgos_sin_nombres(self):
        clave, _ = self.nueva_clave()
        code, _, b = self.api("/api/v1/hallazgos?decision=aceptado", clave)
        r = json.loads(b)
        self.assertEqual((code, r["total"]), (200, 1))
        self.assertEqual(r["datos"][0]["documento"], "A")
        todo = self.api("/api/v1/hallazgos", clave)[2].decode()
        for nombre in ("Marina", "Nelson", "Sergio"):
            self.assertNotIn(nombre, todo)

    def test_alcance(self):
        clave, _ = self.nueva_clave(alcances=("metricas",))
        code, _, b = self.api("/api/v1/hallazgos", clave)
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(b)["error"]["codigo"], "sin_permiso")

    def test_ritmo(self):
        servidor.API_RITMO = (3, 60.0)
        clave, _ = self.nueva_clave()
        codigos = [self.api("/api/v1/documentos", clave)[0] for _ in range(4)]
        self.assertEqual(codigos, [200, 200, 200, 429])
        self.assertIn("Retry-After", self.api("/api/v1/documentos", clave)[1])

    def test_revocar_y_registro(self):
        clave, reg = self.nueva_clave()
        self.assertEqual(self.api("/api/v1/documentos", clave)[0], 200)
        guardada = servidor._estado["claves_api"][reg["id"]]
        self.assertEqual(guardada["usos"], 1)
        code, r = self.post(self.entrar("marina@airbus.es"), "/api/claves/revocar", {"id": reg["id"]})
        self.assertEqual(code, 200, r)
        self.assertEqual(self.api("/api/v1/documentos", clave)[0], 401)
        servidor._guardar()
        self.assertNotIn(clave, servidor.DATOS.read_text(encoding="utf-8"))   # la clave en claro no se guarda nunca

    def test_sigue_las_protecciones_de_red(self):
        clave, _ = self.nueva_clave()
        self.assertEqual(self.api("/api/v1/documentos", clave, host="evil.example")[0], 403)

    def test_mi_cuenta_lista_las_claves(self):
        _, reg = self.nueva_clave()
        _, _, b = self.pedir("GET", "/api/estado", cab={"X-Sesion": self.entrar("marina@airbus.es")})
        lista = json.loads(b)["claves_api"]
        self.assertEqual([c["id"] for c in lista], [reg["id"]])
        self.assertNotIn("huella", lista[0])


if __name__ == "__main__":
    unittest.main()
