"""
Revisión EN EQUIPO y en vivo de la pantalla de hallazgos (sin instalar nada: solo la biblioteca estándar).

    .\\.venv\\Scripts\\python servidor.py            # después de generar_revision.py

Sirve salidas/revision/ en http://<tu-IP>:8765 para los compañeros de la misma red (o de la misma red de Radmin VPN).
Guarda en salidas/colaboracion.json, compartido por todos:
  - decisiones (aprobar / rechazar con comentario), con quién y cuándo;
  - comentarios por hallazgo, con @menciones → avisos (la campanita);
  - presencia: quién está mirando cada hallazgo («Marina también está en este hallazgo»);
  - equipo con roles (Administrador, Aprobador, Revisor);
  - chats de tres tipos:
      canal   público para todo el equipo; solo el administrador del equipo lo crea, renombra o borra;
      grupo   lo crea cualquiera y elige quién entra; su creador es administrador del grupo (renombra,
              añade o quita miembros, da o quita el rol de administrador del grupo);
      privado conversación entre dos personas; solo ellas la ven.
El servidor solo envía a cada persona los chats y mensajes que puede ver. Aviso: el inicio de sesión es de prototipo
(no comprueba contraseñas), así que la privacidad depende de que cada uno entre con su propio correo.
La página pregunta cada 2,5 s si hay novedades. Nada sale de este ordenador; no toca respuestas.csv.
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
ROLES = ("Administrador", "Aprobador", "Revisor")
EQUIPO_INICIAL = [{"n": "Sergio", "c": "sergio@airbus.es", "rol": "Administrador"},
                  {"n": "Marina", "c": "marina@airbus.es", "rol": "Aprobador"},
                  {"n": "Nelson", "c": "nelson@airbus.es", "rol": "Revisor"},
                  {"n": "Valentina", "c": "valentina@airbus.es", "rol": "Revisor"},
                  {"n": "Daniela", "c": "daniela@airbus.es", "rol": "Revisor"}]

_lock = threading.Lock()
_estado = {"seq": 0, "dec": {}, "comentarios": [], "avisos": [], "mensajes": [], "equipo": [dict(m) for m in EQUIPO_INICIAL],
           "chats": [{"id": "general", "tipo": "canal", "nombre": "general", "autor": "", "miembros": {}}], "n_grupos": 0}
_presencia: dict[str, dict] = {}       # usuario → {"key", "t"}


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _cargar():
    global _estado
    if DATOS.exists():
        try:
            datos = json.loads(DATOS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"aviso: {DATOS} no se pudo leer; se empieza vacío (el archivo se conserva)")
            DATOS.rename(DATOS.with_suffix(f".roto-{int(time.time())}.json"))
            return
        if "chats" not in datos:          # versión anterior: «canales» públicos → chats de tipo canal
            autor = datos.get("canal_autor", {})
            datos["chats"] = [{"id": c, "tipo": "canal", "nombre": c, "autor": autor.get(c, ""), "miembros": {}}
                              for c in datos.get("canales", ["general"])]
        datos.pop("canales", None)
        datos.pop("canal_autor", None)
        _estado = {**_estado, **datos}


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


# ------------------------------------------------------------------ chats y permisos
def _chat(cid: str) -> dict | None:
    return next((c for c in _estado["chats"] if c["id"] == cid), None)


def _ve(user: str, c: dict) -> bool:
    return c["tipo"] == "canal" or user in c["miembros"]


def _gestiona(user: str, c: dict) -> bool:
    """Canal: el administrador del equipo. Grupo: un administrador del grupo. Privado: nadie lo renombra."""
    if c["tipo"] == "canal":
        return _rol(user) == "Administrador"
    if c["tipo"] == "grupo":
        return c["miembros"].get(user) == "admin"
    return False


def _miembros_validos(m: dict) -> dict:
    nombres = {x["n"] for x in _estado["equipo"]}
    return {str(n): ("admin" if r == "admin" else "miembro") for n, r in (m or {}).items() if n in nombres}


def _borrar_chat(cid: str):
    _estado["chats"] = [c for c in _estado["chats"] if c["id"] != cid]
    _estado["mensajes"] = [m for m in _estado["mensajes"] if m["canal"] != cid]
    _estado["avisos"] = [a for a in _estado["avisos"] if a["key"] != f"chat:{cid}"]


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
            chats = [c for c in _estado["chats"] if _ve(user, c)]          # cada uno solo recibe lo que puede ver
            ids = {c["id"] for c in chats}
            self._json({"seq": _estado["seq"], "dec": _estado["dec"], "comentarios": _estado["comentarios"],
                        "avisos": [a for a in _estado["avisos"] if a["para"] == user], "presencia": vivos,
                        "chats": chats, "mensajes": [m for m in _estado["mensajes"] if m["canal"] in ids][-800:],
                        "equipo": _estado["equipo"]})

    def do_POST(self):
        u = urlparse(self.path).path
        d = self._cuerpo()
        user = str(d.get("user", ""))[:80].strip()
        if not user:
            return self._json({"error": "falta el usuario"}, 400)
        extra = {}
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
            elif u == "/api/mensaje":
                texto = str(d.get("texto", "")).strip()[:MAX_TEXTO]
                c = _chat(str(d.get("chat") or d.get("canal") or "general"))
                if not texto or not c or not _ve(user, c):
                    return self._json({"error": "mensaje vacío o chat no disponible"}, 400)
                # id único aunque se hayan borrado chats (len()+1 podía repetir el id de un mensaje existente)
                mid = max((m.get("id", 0) for m in _estado["mensajes"]), default=0) + 1
                _estado["mensajes"].append({"id": mid, "canal": c["id"], "user": user, "texto": texto, "fecha": _ahora(),
                                            "vistos": {}})
                mencion = _mencionados(texto, user)
                # Canal público: solo avisa a quien mencionas. Grupo o privado: avisa a todos los que están dentro
                # (como un chat de mensajería); quien está mencionado lo ve marcado como mención.
                avisar = mencion if c["tipo"] == "canal" else (set(c["miembros"]) - {user})
                for p in avisar:
                    _estado["avisos"].append({"para": p, "de": user, "key": f"chat:{c['id']}", "texto": texto[:300],
                                              "fecha": _ahora(), "leido": False, "mid": mid,
                                              "mencion": p in mencion})
            elif u == "/api/chat/crear":
                tipo = d.get("tipo")
                if tipo == "canal":
                    if _rol(user) != "Administrador":
                        return self._json({"error": "solo el administrador del equipo crea canales públicos"}, 403)
                    cid = _nombre_canal(d.get("nombre", ""))
                    if not cid or _chat(cid):
                        return self._json({"error": "nombre vacío o ya existe"}, 400)
                    _estado["chats"].append({"id": cid, "tipo": "canal", "nombre": cid, "autor": user, "miembros": {}})
                elif tipo == "grupo":
                    nombre = str(d.get("nombre", "")).strip()[:40]
                    miembros = _miembros_validos(d.get("miembros"))
                    miembros[user] = "admin"         # quien crea el grupo es su administrador
                    if not nombre or len(miembros) < 2:
                        return self._json({"error": "pon un nombre y al menos otra persona"}, 400)
                    _estado["n_grupos"] = _estado.get("n_grupos", 0) + 1
                    cid = f"g{_estado['n_grupos']}"
                    _estado["chats"].append({"id": cid, "tipo": "grupo", "nombre": nombre, "autor": user, "miembros": miembros})
                elif tipo == "privado":
                    con = str(d.get("con", ""))
                    if con == user or con not in {x["n"] for x in _estado["equipo"]}:
                        return self._json({"error": "elige a otra persona del equipo"}, 400)
                    cid = "dm:" + "|".join(sorted([user, con]))
                    if not _chat(cid):
                        _estado["chats"].append({"id": cid, "tipo": "privado", "nombre": "", "autor": user,
                                                 "miembros": {user: "miembro", con: "miembro"}})
                else:
                    return self._json({"error": "tipo de chat no válido"}, 400)
                extra = {"id": cid}
            elif u == "/api/chat/editar":
                c = _chat(str(d.get("id", "")))
                if not c or not _gestiona(user, c):
                    return self._json({"error": "solo el administrador de este chat puede editarlo"}, 403)
                if "nombre" in d:
                    nombre = str(d.get("nombre", "")).strip()[:40]
                    if not nombre:
                        return self._json({"error": "el nombre no puede quedar vacío"}, 400)
                    c["nombre"] = _nombre_canal(nombre) if c["tipo"] == "canal" else nombre
                if c["tipo"] == "grupo" and "miembros" in d:
                    m = _miembros_validos(d.get("miembros"))
                    if not any(r == "admin" for r in m.values()):
                        return self._json({"error": "el grupo necesita al menos un administrador"}, 400)
                    if len(m) < 2:
                        return self._json({"error": "un grupo necesita al menos dos personas"}, 400)
                    c["miembros"] = m
            elif u == "/api/chat/borrar":
                c = _chat(str(d.get("id", "")))
                if not c or c["id"] == "general":
                    return self._json({"error": "ese chat no se puede eliminar"}, 400)
                if not (_gestiona(user, c) or (c["tipo"] == "privado" and user in c["miembros"])):
                    return self._json({"error": "solo el administrador de este chat puede eliminarlo"}, 403)
                _borrar_chat(c["id"])
            elif u == "/api/chat/salir":
                c = _chat(str(d.get("id", "")))
                if not c or c["tipo"] != "grupo" or user not in c["miembros"]:
                    return self._json({"error": "no estás en ese grupo"}, 400)
                c["miembros"].pop(user)
                if len(c["miembros"]) < 1:
                    _borrar_chat(c["id"])
                elif not any(r == "admin" for r in c["miembros"].values()):
                    c["miembros"][next(iter(c["miembros"]))] = "admin"     # alguien hereda la administración
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
            elif u == "/api/visto":                         # «Visto»: este usuario ha visto en pantalla esos mensajes
                c = _chat(str(d.get("chat", "")))
                if not c or not _ve(user, c):
                    return self._json({"error": "chat no disponible"}, 400)
                ids = {i for i in d.get("ids", [])[:800] if isinstance(i, int)}
                cambio = False
                for m in _estado["mensajes"]:
                    if m["canal"] == c["id"] and m.get("id") in ids and m["user"] != user \
                            and user not in m.setdefault("vistos", {}):
                        m["vistos"][user] = _ahora()
                        cambio = True
                if not cambio:                              # nada nuevo: no se reescribe el archivo ni se avisa a nadie
                    return self._json({"ok": True, "seq": _estado["seq"]})
            elif u == "/api/leido":                         # marca como leídos los avisos (de un chat o todos)
                k = d.get("key")
                for a in _estado["avisos"]:
                    if a["para"] == user and (not k or a["key"] == k):
                        a["leido"] = True
            elif u == "/api/avisos/borrar":                 # quita de la campanita los avisos de un chat (o todos)
                k = d.get("key")
                _estado["avisos"] = [a for a in _estado["avisos"] if not (a["para"] == user and (not k or a["key"] == k))]
            else:
                return self._json({"error": "ruta desconocida"}, 404)
            _estado["seq"] += 1
            _guardar()
            return self._json({"ok": True, "seq": _estado["seq"], **extra})


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
        print(f"  · Compañeros (misma red o Radmin VPN):  http://{ip}:{a.puerto}")
    print("\nSi Windows pregunta por el Firewall, pulsa «Permitir».")
    print("Ctrl+C para pararla. Lo compartido se guarda en salidas\\colaboracion.json.\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Parada.")


if __name__ == "__main__":
    main()
