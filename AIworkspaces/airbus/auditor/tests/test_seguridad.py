"""
Pruebas de las protecciones de red de servidor.py: direcciones permitidas (Host / Origin), tamaño de las
peticiones y adjuntos del chat.

Levantan servidor.py de verdad en un puerto libre, con datos temporales (no tocan salidas/), y le hablan como lo
haría una página ajena o alguien que se salta la interfaz.

Ejecutar desde airbus/auditor:   .venv/bin/python -m unittest tests.test_seguridad -v
                                 (Windows: .\\.venv\\Scripts\\python -m unittest tests.test_seguridad -v)
"""
import copy
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import servidor
from src import permisos as P

ESTADO_INICIAL = copy.deepcopy(servidor._estado)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.domain)</script></svg>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class TestSeguridad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raiz = Path(cls.tmp.name)
        web = raiz / "revision"
        web.mkdir()
        (web / "index.html").write_text('<script>\nconst D={"docs":{},"res":[]};\n</script>', encoding="utf-8")
        cls.antes = {k: getattr(servidor, k) for k in ("WEB", "DATOS", "VERSIONES", "ADJUNTOS")}
        servidor.WEB, servidor.DATOS = web, raiz / "colaboracion.json"
        servidor.VERSIONES, servidor.ADJUNTOS = raiz / "versiones", raiz / "adjuntos"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        cls.puerto = cls.srv.server_address[1]
        cls.host = f"localhost:{cls.puerto}"
        servidor._HOSTS.clear()                      # como al arrancar sin --lan: solo este ordenador
        servidor._HOSTS.update(servidor._hosts_permitidos(cls.puerto, False, []))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        servidor._HOSTS.clear()                      # las demás pruebas arrancan sin comprobar Host
        for k, v in cls.antes.items():
            setattr(servidor, k, v)
        cls.tmp.cleanup()

    def setUp(self):
        e = copy.deepcopy(ESTADO_INICIAL)
        P.migrar(e)
        servidor._estado = e
        servidor._tokens.clear()
        servidor._cargar_documentos()
        self.token = self.json("POST", "/api/login", {"correo": "nelson@airbus.es"})[1]["token"]

    # --- utilidades
    def pedir(self, metodo, ruta, cuerpo=None, cab=None, host=None):
        """Petición con las cabeceras exactas que se indiquen (Host incluido). → (código, cabeceras, cuerpo)"""
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

    def json(self, metodo, ruta, datos=None, cab=None, **k):
        cab = {"Content-Type": "application/json", **(cab or {})}
        if getattr(self, "token", None):
            cab.setdefault("X-Sesion", self.token)
        code, _, b = self.pedir(metodo, ruta, json.dumps(datos or {}).encode() if metodo == "POST" else None, cab, **k)
        try:
            return code, json.loads(b)
        except ValueError:
            return code, {}

    def subir(self, nombre, tipo, datos):
        code, _, b = self.pedir("POST", "/api/subir", datos, {"Content-Type": tipo, "X-Sesion": self.token,
                                                              "X-Chat": quote("general"), "X-Nombre": quote(nombre)})
        return code, json.loads(b)

    def bajar(self, aid, extra=""):
        return self.pedir("GET", f"/api/adjunto?id={aid}&s={self.token}{extra}")

    def mensajes(self):
        return [m["texto"] for m in servidor._estado["mensajes"]]

    # --- direcciones permitidas (DNS rebinding y peticiones desde otra web)
    def test_host_propio_y_ajeno(self):
        self.assertEqual(self.pedir("GET", "/")[0], 200)
        self.assertEqual(self.pedir("GET", "/", host="evil.example")[0], 403)
        self.assertEqual(self.json("GET", "/api/estado", host=f"evil.example:{self.puerto}")[0], 403)
        self.assertEqual(self.pedir("HEAD", "/", host="evil.example")[0], 403)

    def test_post_desde_otra_web_se_rechaza(self):
        m = {"chat": "general", "texto": "csrf"}
        self.assertEqual(self.json("POST", "/api/mensaje", m, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.json("POST", "/api/mensaje", m, {"Origin": "null"})[0], 403)
        self.assertEqual(self.json("POST", "/api/mensaje", m, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.json("POST", "/api/login", {"correo": "sergio@airbus.es"}, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.mensajes(), [])

    def test_post_de_la_propia_pagina_pasa(self):
        code, j = self.json("POST", "/api/mensaje", {"chat": "general", "texto": "hola"}, {"Origin": f"http://{self.host}"})
        self.assertEqual(code, 200, j)
        self.assertEqual(self.mensajes(), ["hola"])

    def test_post_simple_sin_json_declarado_se_rechaza(self):
        """text/plain no necesita «preflight»: es lo que usaría otra web para colar una petición."""
        cuerpo = json.dumps({"chat": "general", "texto": "csrf"}).encode()
        code, _, _ = self.pedir("POST", "/api/mensaje", cuerpo, {"Content-Type": "text/plain", "X-Sesion": self.token})
        self.assertEqual(code, 415)
        self.assertEqual(self.mensajes(), [])

    def test_direcciones_con_y_sin_lan(self):
        solo = servidor._hosts_permitidos(8765, False, [])
        self.assertEqual(solo, {"localhost:8765", "127.0.0.1:8765", "[::1]:8765"})
        lan = servidor._hosts_permitidos(8765, True, ["Revision.Equipo.es", "proxy.local:443"])
        self.assertLess(solo, lan)
        for ip in servidor.ips_locales():
            self.assertIn(f"{ip}:8765", lan)
        self.assertLessEqual({"revision.equipo.es", "revision.equipo.es:8765", "proxy.local:443"}, lan)

    # --- tamaño de las peticiones
    def test_content_length_negativo_no_cuelga_el_servidor(self):
        t0 = time.time()
        s = socket.create_connection(("127.0.0.1", self.puerto), timeout=5)
        s.sendall(f"POST /api/mensaje HTTP/1.1\r\nHost: {self.host}\r\nContent-Type: application/json\r\n"
                  f"X-Sesion: {self.token}\r\nContent-Length: -1\r\n\r\n".encode())
        resp = s.recv(200).decode(errors="replace")
        s.close()
        self.assertIn(" 413 ", resp)
        self.assertLess(time.time() - t0, 3)

    def test_content_length_enorme_o_no_numerico(self):
        for valor in ("999999999", "abc"):
            code, _, _ = self.pedir("POST", "/api/mensaje", b"", {"Content-Type": "application/json", "X-Sesion": self.token,
                                                                   "Content-Length": valor})
            self.assertEqual(code, 413, valor)

    def test_json_que_no_es_un_objeto_no_rompe(self):
        code, _, _ = self.pedir("POST", "/api/mensaje", b"[1,2,3]", {"Content-Type": "application/json", "X-Sesion": self.token})
        self.assertEqual(code, 400)

    # --- adjuntos del chat
    def test_svg_con_script_solo_se_descarga(self):
        code, j = self.subir("logo.svg", "image/svg+xml", SVG)
        self.assertEqual((code, j["tipo"]), (200, "application/octet-stream"))
        code, h, b = self.bajar(j["id"])
        self.assertEqual((code, h["Content-Type"], b), (200, "application/octet-stream", SVG))
        self.assertTrue(h["Content-Disposition"].startswith("attachment"))

    def test_el_tipo_sale_del_contenido_no_de_lo_declarado(self):
        self.assertEqual(self.subir("foto.png", "image/png", b"<html><script>alert(1)</script></html>")[1]["tipo"],
                         "application/octet-stream")
        self.assertEqual(self.subir("pagina.html", "text/html", PNG)[1]["tipo"], "image/png")
        self.assertEqual(self.subir("binario.txt", "text/plain", b"MZ\x90\x00\x03\x00")[1]["tipo"], "application/octet-stream")
        self.assertEqual(self.subir("doc.pdf", "application/pdf", b"%PDF-1.7\n")[1]["tipo"], "application/pdf")

    def test_imagen_en_linea_con_cabeceras_de_proteccion(self):
        aid = self.subir("foto.png", "image/png", PNG)[1]["id"]
        _, h, _ = self.bajar(aid)
        self.assertEqual(h["Content-Type"], "image/png")
        self.assertTrue(h["Content-Disposition"].startswith("inline"))
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(h["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(h["Referrer-Policy"], "no-referrer")
        self.assertTrue(h["Content-Security-Policy"].startswith("sandbox"))
        self.assertTrue(self.bajar(aid, "&descargar=1")[1]["Content-Disposition"].startswith("attachment"))

    def test_texto_y_pdf(self):
        aid = self.subir("notas.txt", "text/plain", "<script>alert(1)</script> año".encode())[1]["id"]
        self.assertEqual(self.bajar(aid)[1]["Content-Type"], "text/plain; charset=utf-8")
        aid = self.subir("informe_año_文.pdf", "application/pdf", b"%PDF-1.7\n")[1]["id"]
        code, h, _ = self.bajar(aid)                   # un nombre con caracteres no latinos rompía la respuesta
        self.assertEqual(code, 200)
        self.assertIn("filename*=UTF-8''", h["Content-Disposition"])
        self.assertNotIn("Content-Security-Policy", h)  # el visor de PDF del navegador no funciona en un «sandbox»

    def test_adjunto_antiguo_con_tipo_peligroso_se_descarga(self):
        """Adjuntos guardados antes de este cambio, con el tipo que declaró quien los subió."""
        servidor.ADJUNTOS.mkdir(parents=True, exist_ok=True)
        (servidor.ADJUNTOS / "viejo.svg").write_bytes(SVG)
        servidor._estado["adjuntos"]["viejo"] = {"nombre": "viejo.svg", "tipo": "image/svg+xml", "tam": len(SVG),
                                                 "chat": "general", "user": "Nelson", "fecha": "", "archivo": "viejo.svg"}
        _, h, _ = self.bajar("viejo")
        self.assertEqual(h["Content-Type"], "application/octet-stream")
        self.assertTrue(h["Content-Disposition"].startswith("attachment"))

    def test_identificadores_y_nombres_en_disco(self):
        ids = [self.subir(f"a{i}.png", "image/png", PNG)[1]["id"] for i in range(3)]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(len(i) == 16 for i in ids), ids)
        aid = self.subir("a.txt:flujo", "text/plain", b"hola")[1]["id"]     # extensión rara: no llega al disco
        self.assertEqual(servidor._estado["adjuntos"][aid]["archivo"], aid)
        self.assertEqual(self.subir("vacio.png", "image/png", b"")[0], 400)

    def test_adjunto_sin_sesion_no_se_sirve(self):
        aid = self.subir("foto.png", "image/png", PNG)[1]["id"]
        self.assertEqual(self.pedir("GET", f"/api/adjunto?id={aid}")[0], 404)


if __name__ == "__main__":
    unittest.main()
