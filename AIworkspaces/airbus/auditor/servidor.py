"""
Revisión EN EQUIPO y en vivo de la pantalla de hallazgos (sin instalar nada: solo la biblioteca estándar).

    .\\.venv\\Scripts\\python servidor.py            # después de generar_revision.py

Sirve salidas/revision/ en http://<tu-IP>:8765 para que los compañeros de la MISMA red Wi-Fi la abran en su navegador.
Guarda en salidas/colaboracion.json, compartido por todos:
  - decisiones (aprobar / rechazar con comentario), con quién y cuándo;
  - comentarios por hallazgo, con @menciones → avisos (la campanita);
  - presencia: quién está mirando cada hallazgo («Marina también está en este hallazgo»).
La página pregunta cada 2,5 s si hay novedades. Nada sale de este ordenador; no toca respuestas.csv.
Abierta con doble clic (sin servidor), la página sigue funcionando sola, guardando en el navegador.
"""
import argparse
import json
import re
import socket
import threading
import time
import unicodedata
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "salidas" / "revision"
DATOS = RAIZ / "salidas" / "colaboracion.json"
PRESENCIA_S = 20          # segundos sin señal para dejar de mostrar a alguien como presente
MAX_TEXTO = 2000

# Equipo inicial (después se gestiona desde Configuración → Usuarios y roles; se guarda en colaboracion.json).
# Se puede mencionar a cualquier miembro aunque todavía no se haya conectado.
ROLES = ("Administrador", "Aprobador", "Revisor")
EQUIPO_INICIAL = [{"n": "Sergio", "c": "sergio@airbus.es", "rol": "Administrador"},
                  {"n": "Marina", "c": "marina@airbus.es", "rol": "Aprobador"},
                  {"n": "Nelson", "c": "nelson@airbus.es", "rol": "Revisor"},
                  {"n": "Valentina", "c": "valentina@airbus.es", "rol": "Revisor"},
                  {"n": "Daniela", "c": "daniela@airbus.es", "rol": "Revisor"}]

_lock = threading.Lock()
_estado = {"seq": 0, "dec": {}, "comentarios": [], "avisos": [], "mensajes": [], "canales": ["general"],
           "canal_autor": {}, "equipo": [dict(m) for m in EQUIPO_INICIAL]}
_presencia: dict[str, dict] = {}       # usuario → {"key", "t"}


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _cargar():
    global _estado
    if DATOS.exists():
        try:
            _estado = {**_estado, **json.loads(DATOS.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            print(f"aviso: {DATOS} no se pudo leer; se empieza vacío (el archivo se conserva)")
            DATOS.rename(DATOS.with_suffix(f".roto-{int(time.time())}.json"))


def _guardar():
    tmp = DATOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(_estado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATOS)


def _usuarios() -> set[str]:
    u = {d.get("user", "") for d in _estado["dec"].values()} | {c["user"] for c in _estado["comentarios"]}
    u |= {m["user"] for m in _estado["mensajes"]} | {m["n"] for m in _estado["equipo"]}
    return {x for x in u | set(_presencia) if x}


def _rol(user: str) -> str:
    return next((m["rol"] for m in _estado["equipo"] if m["n"] == user), "")


def _nombre_canal(t: str) -> str:
    return re.sub(r"[^a-z0-9ñ\-]", "", _norm(str(t)).strip().replace(" ", "-"))[:30]


def _mencionados(texto: str, autor: str) -> set[str]:
    """@nombre o @nombre.apellido → usuarios conocidos cuyo nombre empieza así (sin mayúsculas ni tildes)."""
    salida = set()
    for m in re.findall(r"@([\wáéíóúñü.\-]+)", texto, re.I):
        clave = _norm(m).replace(".", " ").replace("-", " ").strip()
        for u in _usuarios():
            if u != autor and _norm(u).startswith(clave):
                salida.add(u)
    return salida


class Manejador(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def log_message(self, *_):            # sin ruido en la consola
        pass

    def _json(self, datos, code=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _cuerpo(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 20000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path != "/api/estado":
            return super().do_GET()
        q = parse_qs(u.query)
        user = (q.get("user") or [""])[0][:80]
        key = (q.get("key") or [""])[0][:200]
        with _lock:
            if user:
                _presencia[user] = {"key": key, "t": time.time()}
            vivos = {n: p["key"] for n, p in _presencia.items() if time.time() - p["t"] < PRESENCIA_S}
            self._json({"seq": _estado["seq"], "dec": _estado["dec"], "comentarios": _estado["comentarios"],
                        "avisos": [a for a in _estado["avisos"] if a["para"] == user], "presencia": vivos,
                        "mensajes": _estado["mensajes"][-500:], "canales": _estado["canales"],
                        "canal_autor": _estado["canal_autor"], "equipo": _estado["equipo"]})

    def do_POST(self):
        u = urlparse(self.path).path
        d = self._cuerpo()
        user = str(d.get("user", ""))[:80].strip()
        if not user:
            return self._json({"error": "falta el usuario"}, 400)
        with _lock:
            if u == "/api/decision":
                for key in d.get("keys", [])[:500]:
                    _estado["dec"][str(key)[:200]] = {"dec": d.get("dec") if d.get("dec") in ("approved", "rejected") else "approved",
                                                       "note": str(d.get("note", ""))[:MAX_TEXTO], "user": user, "fecha": _ahora()}
            elif u == "/api/deshacer":
                _estado["dec"].pop(str(d.get("key", "")), None)
            elif u == "/api/comentario":
                texto = str(d.get("texto", "")).strip()[:MAX_TEXTO]
                key = str(d.get("key", ""))[:200]
                if not texto or not key:
                    return self._json({"error": "comentario vacío"}, 400)
                cid = len(_estado["comentarios"]) + 1
                _estado["comentarios"].append({"id": cid, "key": key, "user": user, "texto": texto, "fecha": _ahora()})
                for p in _mencionados(texto, user):
                    _estado["avisos"].append({"para": p, "de": user, "key": key, "texto": texto[:300],
                                              "fecha": _ahora(), "leido": False, "cid": cid})
            elif u == "/api/mensaje":                       # chat del equipo, por canales
                texto = str(d.get("texto", "")).strip()[:MAX_TEXTO]
                canal = str(d.get("canal", "general"))[:40]
                if not texto or canal not in _estado["canales"]:
                    return self._json({"error": "mensaje vacío o canal inexistente"}, 400)
                mid = len(_estado["mensajes"]) + 1
                _estado["mensajes"].append({"id": mid, "canal": canal, "user": user, "texto": texto, "fecha": _ahora()})
                for p in _mencionados(texto, user):
                    _estado["avisos"].append({"para": p, "de": user, "key": f"chat:{canal}", "texto": texto[:300],
                                              "fecha": _ahora(), "leido": False, "mid": mid})
            elif u == "/api/canal":
                nombre = _nombre_canal(d.get("nombre", ""))
                if not nombre:
                    return self._json({"error": "nombre de canal vacío"}, 400)
                if nombre not in _estado["canales"]:
                    _estado["canales"].append(nombre)
                    _estado["canal_autor"][nombre] = user
            elif u in ("/api/canal/renombrar", "/api/canal/borrar"):
                # Solo quien creó el chat o un administrador; #general no se toca
                de = str(d.get("nombre", ""))
                if de not in _estado["canales"] or de == "general":
                    return self._json({"error": "ese chat no se puede modificar"}, 400)
                if user != _estado["canal_autor"].get(de) and _rol(user) != "Administrador":
                    return self._json({"error": "solo quien creó el chat o un administrador"}, 403)
                if u.endswith("borrar"):
                    _estado["canales"].remove(de)
                    _estado["mensajes"] = [m for m in _estado["mensajes"] if m["canal"] != de]
                    _estado["avisos"] = [a for a in _estado["avisos"] if a["key"] != f"chat:{de}"]
                else:
                    a = _nombre_canal(d.get("nuevo", ""))
                    if not a or a in _estado["canales"]:
                        return self._json({"error": "nombre vacío o ya existe"}, 400)
                    _estado["canales"][_estado["canales"].index(de)] = a
                    _estado["canal_autor"][a] = _estado["canal_autor"].pop(de, user)
                    for m in _estado["mensajes"]:
                        if m["canal"] == de:
                            m["canal"] = a
                    for av in _estado["avisos"]:
                        if av["key"] == f"chat:{de}":
                            av["key"] = f"chat:{a}"
            elif u in ("/api/equipo/alta", "/api/equipo/baja", "/api/equipo/rol"):
                if _rol(user) != "Administrador":
                    return self._json({"error": "solo un administrador gestiona el equipo"}, 403)
                eq = _estado["equipo"]
                n = str(d.get("n", "")).strip()[:40]
                if u.endswith("alta"):
                    c = str(d.get("c", "")).strip().lower()[:80]
                    rol = d.get("rol") if d.get("rol") in ROLES else "Revisor"
                    if not n or "@" not in c:
                        return self._json({"error": "faltan el nombre o un correo válido"}, 400)
                    if any(_norm(m["n"]) == _norm(n) or m["c"] == c for m in eq):
                        return self._json({"error": "ya hay alguien con ese nombre o correo"}, 400)
                    eq.append({"n": n, "c": c, "rol": rol})
                elif u.endswith("baja"):
                    if n == user:
                        return self._json({"error": "no puedes eliminarte a ti mismo"}, 400)
                    _estado["equipo"] = [m for m in eq if m["n"] != n]
                else:
                    rol = d.get("rol")
                    if rol not in ROLES:
                        return self._json({"error": "rol no válido"}, 400)
                    admins = [m for m in eq if m["rol"] == "Administrador"]
                    if rol != "Administrador" and len(admins) == 1 and admins[0]["n"] == n:
                        return self._json({"error": "tiene que quedar al menos un administrador"}, 400)
                    for m in eq:
                        if m["n"] == n:
                            m["rol"] = rol
            elif u == "/api/leido":
                for a in _estado["avisos"]:
                    if a["para"] == user:
                        a["leido"] = True
            else:
                return self._json({"error": "ruta desconocida"}, 404)
            _estado["seq"] += 1
            _guardar()
            return self._json({"ok": True, "seq": _estado["seq"]})


def ips_locales() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))          # no envía nada: solo elige la interfaz de red
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8765)
    a = ap.parse_args()
    if not (WEB / "index.html").exists():
        raise SystemExit("\nTodavía no está generada la pantalla.\n  → Ejecuta primero: .\\.venv\\Scripts\\python generar_revision.py\n")
    _cargar()
    srv = ThreadingHTTPServer(("0.0.0.0", a.puerto), Manejador)
    print("\nRevisión en equipo en marcha. Ábrela en el navegador:")
    print(f"  · En este ordenador:   http://localhost:{a.puerto}")
    for ip in ips_locales():
        print(f"  · Compañeros (misma Wi-Fi):  http://{ip}:{a.puerto}")
    print("\nSi Windows pregunta por el Firewall, pulsa «Permitir» (redes privadas).")
    print("Ctrl+C para pararla. Lo compartido se guarda en salidas\\colaboracion.json.\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Parada.")


if __name__ == "__main__":
    main()
