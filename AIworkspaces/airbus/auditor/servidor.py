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
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "salidas" / "revision"
DATOS = RAIZ / "salidas" / "colaboracion.json"
PRESENCIA_S = 20          # segundos sin señal para dejar de mostrar a alguien como presente
MAX_TEXTO = 2000
ADJUNTOS = RAIZ / "salidas" / "adjuntos"      # archivos enviados en el chat (solo se sirven a quien ve ese chat)
MAX_ADJUNTO = 25 * 1024 * 1024                # 25 MB por archivo
# Asistente IA con RAG local (AIworkspaces/_rag/servidor_rag.py: ChromaDB + Llama en Ollama). Si no está encendido,
# el botón «Asistente IA» sigue funcionando con su búsqueda dentro de la app.
ASISTENTE_URL = "http://127.0.0.1:8766/preguntar"
TIPOS_EN_LINEA = ("image/", "video/", "audio/", "application/pdf", "text/plain")

# Equipo inicial (después se gestiona desde Configuración → Usuarios y roles; se guarda en colaboracion.json).
ROLES = ("Administrador", "Aprobador", "Revisor")
EDITAR_MIN = 30           # minutos durante los que se puede editar un mensaje del chat (la página usa el mismo valor)
EQUIPO_INICIAL = [{"n": "Sergio", "c": "sergio@airbus.es", "rol": "Administrador"},
                  {"n": "Marina", "c": "marina@airbus.es", "rol": "Aprobador"},
                  {"n": "Nelson", "c": "nelson@airbus.es", "rol": "Revisor"},
                  {"n": "Valentina", "c": "valentina@airbus.es", "rol": "Revisor"},
                  {"n": "Daniela", "c": "daniela@airbus.es", "rol": "Revisor"}]

_lock = threading.Lock()
_estado = {"seq": 0, "dec": {}, "comentarios": [], "avisos": [], "mensajes": [], "equipo": [dict(m) for m in EQUIPO_INICIAL],
           "chats": [{"id": "general", "tipo": "canal", "nombre": "general", "autor": "", "miembros": {}}], "n_grupos": 0,
           "adjuntos": {},       # id → {nombre, tipo, tam, chat, user, fecha, archivo}
           "ediciones": {},      # clave del hallazgo → [{user, fecha, tipo, clausula, justificacion}] (el original no se toca)
           "versiones": {},      # documento → [{n, user, fecha, nota, nombre, base, paginas}]; el texto va aparte
           "docs_meta": {},      # documento → {prioridad: {valor, user, fecha}, revisado: {user, fecha}}
           "compartidos": [],    # [{doc, de, para: [..], nota, fecha}]
           "cargados": {}}       # id → {archivo, tipo, vista, paginas, codigo, version, titulo, familia, prioridad, user, fecha}
PRIORIDADES = ("Alta", "Media", "Baja")
DOC_ID = re.compile(r"[\w.\-]{1,120}")       # códigos de documento válidos (sin barras: también nombran archivos)
VERSIONES = RAIZ / "salidas" / "versiones"   # un JSON por versión; el PDF original del corpus nunca se modifica
MAX_VERSION = 3_000_000                      # bytes del cuerpo al guardar una versión (el resto de peticiones: 20 KB)
_presencia: dict[str, dict] = {}       # usuario → {"key", "t"}
_sesiones: dict[str, dict] = {}        # usuario → {id de sesión → {"inicio", "ua", "t"}} (en memoria; solo informativo)
SESION_S = 30 * 60                     # una sesión sin señales durante 30 min deja de listarse
_sid_cerrados: dict[str, float] = {}   # sesiones cerradas: un sondeo que llegue tarde no las vuelve a «abrir»


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
    for aid, meta in list(_estado["adjuntos"].items()):          # sus archivos adjuntos también se borran
        if meta["chat"] == cid:
            (ADJUNTOS / meta["archivo"]).unlink(missing_ok=True)
            _estado["adjuntos"].pop(aid)
    _estado["chats"] = [c for c in _estado["chats"] if c["id"] != cid]
    _estado["mensajes"] = [m for m in _estado["mensajes"] if m["canal"] != cid]
    _estado["avisos"] = [a for a in _estado["avisos"] if a["key"] != f"chat:{cid}"]


def _borrar_cargado(cid: str):
    """Quita los archivos de un documento cargado (original, contenido e imágenes/texto de sus páginas)."""
    import shutil
    if not re.fullmatch(r"[0-9a-f]+", cid):
        return
    shutil.rmtree(WEB / "cargados" / cid, ignore_errors=True)
    for f in (WEB / "paginas").glob(f"up_{cid}_*"):
        f.unlink(missing_ok=True)


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

    def _cuerpo(self, limite: int = 20000) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > limite:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    def _adjunto(self, q):
        """Descarga o muestra un archivo del chat, solo si quien lo pide puede ver ese chat."""
        aid = (q.get("id") or [""])[0]
        user = (q.get("user") or [""])[0][:80]
        with _lock:
            meta = _estado["adjuntos"].get(aid)
            c = _chat(meta["chat"]) if meta else None
            if not meta or not c or not _ve(user, c):
                return self._json({"error": "archivo no disponible"}, 404)
        ruta = ADJUNTOS / meta["archivo"]
        if not ruta.exists():
            return self._json({"error": "archivo no encontrado"}, 404)
        datos = ruta.read_bytes()
        en_linea = meta["tipo"].startswith(TIPOS_EN_LINEA) and (q.get("descargar") or ["0"])[0] != "1"
        nombre = re.sub(r'[^\w.\- ]', "_", meta["nombre"])
        self.send_response(200)
        self.send_header("Content-Type", meta["tipo"] or "application/octet-stream")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Content-Disposition", f'{"inline" if en_linea else "attachment"}; filename="{nombre}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(datos)

    def _subir(self):
        """Recibe un archivo (cuerpo binario) para adjuntarlo a un mensaje del chat."""
        from urllib.parse import unquote
        user = unquote(self.headers.get("X-User", ""))[:80].strip()
        chat = unquote(self.headers.get("X-Chat", ""))[:200]
        nombre = unquote(self.headers.get("X-Nombre", "archivo"))[:120] or "archivo"
        tipo = (self.headers.get("Content-Type") or "application/octet-stream").split(";")[0][:100]
        n = int(self.headers.get("Content-Length", 0) or 0)
        with _lock:
            c = _chat(chat)
            permitido = bool(user and c and _ve(user, c))
        if not permitido or n <= 0 or n > MAX_ADJUNTO:
            self.close_connection = True          # no se lee el cuerpo: se cierra la conexión
            if not permitido:
                return self._json({"error": "no puedes adjuntar en ese chat"}, 403)
            return self._json({"error": "el archivo está vacío o pasa de 25 MB"}, 400)
        datos = self.rfile.read(n)
        aid = f"{int(time.time() * 1000):x}{len(_estado['adjuntos']):x}"
        ext = Path(nombre).suffix.lower()[:10]
        ADJUNTOS.mkdir(parents=True, exist_ok=True)
        (ADJUNTOS / f"{aid}{ext}").write_bytes(datos)
        with _lock:
            _estado["adjuntos"][aid] = {"nombre": nombre, "tipo": tipo, "tam": n, "chat": chat, "user": user,
                                        "fecha": _ahora(), "archivo": f"{aid}{ext}"}
            _guardar()
        return self._json({"ok": True, "id": aid, "nombre": nombre, "tipo": tipo, "tam": n})

    def _cargar(self):
        """«Cargar archivo» en Inicio: guarda el original y lo prepara para abrirlo en Revisión (src/cargados.py).
        Queda pendiente de confirmar (familia y prioridad) con /api/cargado/guardar."""
        from urllib.parse import unquote
        user = unquote(self.headers.get("X-User", ""))[:80].strip()
        nombre = Path(unquote(self.headers.get("X-Nombre", "documento"))[:120]).name or "documento"
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not user or n <= 0 or n > MAX_ADJUNTO:
            self.close_connection = True
            return self._json({"error": "falta el usuario, o el archivo está vacío o pasa de 25 MB"}, 400)
        datos = self.rfile.read(n)
        with _lock:
            cid = f"{int(time.time() * 1000):x}{len(_estado.setdefault('cargados', {})):x}"
        seguro = re.sub(r"[^\w.\- ]", "_", nombre)
        carpeta = WEB / "cargados" / cid
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / seguro).write_bytes(datos)
        try:                                        # fuera del candado: un PDF grande no bloquea el chat de nadie
            from src import cargados
            meta = cargados.procesar(carpeta / seguro, cid, WEB)
            tipo = cargados.tipo_de(nombre)
        except Exception as e:
            _borrar_cargado(cid)
            return self._json({"error": f"no se pudo preparar el documento: {type(e).__name__}: {e}"[:300]}, 400)
        with _lock:
            _estado["cargados"][cid] = {"archivo": nombre, "ruta": f"cargados/{cid}/{seguro}", "tipo": tipo, "tam": n,
                                        "user": user, "fecha": _ahora(), "confirmado": False, **meta}
            _guardar()
        return self._json({"ok": True, "id": cid, **_estado["cargados"][cid]})

    def _asistente(self, d):
        """Reenvía la pregunta al servicio RAG local y devuelve {respuesta, fuentes} (o un error legible)."""
        cuerpo = json.dumps({"pregunta": str(d.get("pregunta", ""))[:2000], "datos_app": str(d.get("datos_app", ""))[:6000],
                             "historial": d.get("historial") or []}, ensure_ascii=False).encode()
        try:
            with urlopen(Request(ASISTENTE_URL, data=cuerpo, headers={"Content-Type": "application/json"}), timeout=180) as r:
                return self._json(json.loads(r.read()))
        except Exception as e:
            return self._json({"error": "El asistente con IA no está encendido (ejecuta _rag/servidor_rag.py y abre Ollama). "
                                        f"Detalle: {type(e).__name__}"}, 503)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/adjunto":
            return self._adjunto(parse_qs(u.query))
        if u.path == "/api/version":                  # texto completo de una versión (la lista va en /api/estado)
            q = parse_qs(u.query)
            doc, n = (q.get("doc") or [""])[0], (q.get("n") or [""])[0]
            f = VERSIONES / f"{doc}_v{n}.json"
            if not re.fullmatch(r"[\w.\-]+", doc) or not n.isdigit() or not f.exists():
                return self._json({"error": "versión no encontrada"}, 404)
            return self._json(json.loads(f.read_text(encoding="utf-8")))
        if u.path != "/api/estado":
            return super().do_GET()
        q = parse_qs(u.query)
        user = (q.get("user") or [""])[0][:80]
        key = (q.get("key") or [""])[0][:200]
        sid = (q.get("sid") or [""])[0][:40]
        with _lock:
            cerrada = sid in _sid_cerrados
            if user and not cerrada:
                _presencia[user] = {"key": key, "t": time.time()}
            if user and sid and not cerrada:                  # «Mi cuenta → Sesiones abiertas»: cada pestaña del navegador es una sesión
                s = _sesiones.setdefault(user, {}).setdefault(sid, {"inicio": _ahora(), "ua": self.headers.get("User-Agent", "")[:300]})
                s["t"] = time.time()
            ahora_t = time.time()
            mias = sorted(({"sid": k, "inicio": v["inicio"], "ua": v["ua"], "hace_s": int(ahora_t - v["t"])}
                           for k, v in _sesiones.get(user, {}).items() if ahora_t - v["t"] < SESION_S),
                          key=lambda x: x["hace_s"])
            vivos = {n: p["key"] for n, p in _presencia.items() if time.time() - p["t"] < PRESENCIA_S}
            chats = [c for c in _estado["chats"] if _ve(user, c)]          # cada uno solo recibe lo que puede ver
            ids = {c["id"] for c in chats}
            vaciado = _estado.setdefault("vaciados", {}).get(user, {})     # «Vaciar chat» es solo para quien lo pide
            visibles = [m for m in _estado["mensajes"]
                        if m["canal"] in ids and m.get("id", 0) > vaciado.get(m["canal"], 0)]
            self._json({"seq": _estado["seq"], "dec": _estado["dec"], "comentarios": _estado["comentarios"],
                        "avisos": [a for a in _estado["avisos"] if a["para"] == user], "presencia": vivos,
                        "chats": chats, "mensajes": visibles[-800:],
                        "equipo": _estado["equipo"], "ediciones": _estado["ediciones"],
                        "versiones": _estado.get("versiones", {}), "sesiones": mias,
                        "docs_meta": _estado.get("docs_meta", {}),
                        "compartidos": [x for x in _estado.get("compartidos", []) if user == x["de"] or user in x["para"]],
                        "cargados": [{"id": k, **v} for k, v in _estado.get("cargados", {}).items() if v.get("confirmado")]})

    def do_POST(self):
        u = urlparse(self.path).path
        if u == "/api/subir":
            return self._subir()
        if u == "/api/cargar":
            return self._cargar()
        d = self._cuerpo(MAX_VERSION if u == "/api/version/guardar" else 20000)
        if u == "/api/asistente":
            return self._asistente(d)
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
                # Solo se adjuntan archivos subidos por esta persona a este mismo chat
                adj = [{"id": a, **{k: _estado["adjuntos"][a][k] for k in ("nombre", "tipo", "tam")}}
                       for a in d.get("adjuntos", [])[:10]
                       if a in _estado["adjuntos"] and _estado["adjuntos"][a]["user"] == user
                       and c and _estado["adjuntos"][a]["chat"] == c["id"]]
                if not (texto or adj) or not c or not _ve(user, c):
                    return self._json({"error": "mensaje vacío o chat no disponible"}, 400)
                # id único aunque se hayan borrado chats (len()+1 podía repetir el id de un mensaje existente)
                mid = max((m.get("id", 0) for m in _estado["mensajes"]), default=0) + 1
                _estado["mensajes"].append({"id": mid, "canal": c["id"], "user": user, "texto": texto, "fecha": _ahora(),
                                            "vistos": {}, **({"adjuntos": adj} if adj else {})})
                if not texto:
                    texto = "📎 " + ", ".join(a["nombre"] for a in adj)
                mencion = _mencionados(texto, user)
                # Canal público: solo avisa a quien mencionas. Grupo o privado: avisa a todos los que están dentro
                # (como un chat de mensajería); quien está mencionado lo ve marcado como mención.
                avisar = mencion if c["tipo"] == "canal" else (set(c["miembros"]) - {user})
                for p in avisar:
                    _estado["avisos"].append({"para": p, "de": user, "key": f"chat:{c['id']}", "texto": texto[:300],
                                              "fecha": _ahora(), "leido": False, "mid": mid,
                                              "mencion": p in mencion})
            elif u == "/api/mensaje/editar":                # cada uno edita solo sus propios mensajes
                m = next((x for x in _estado["mensajes"] if x["id"] == d.get("id")), None)
                texto = str(d.get("texto", "")).strip()[:MAX_TEXTO]
                if not m or m["user"] != user:
                    return self._json({"error": "solo puedes editar tus propios mensajes"}, 403)
                if (datetime.now() - datetime.fromisoformat(m["fecha"])).total_seconds() > EDITAR_MIN * 60:
                    return self._json({"error": f"solo se puede editar un mensaje durante {EDITAR_MIN} minutos"}, 403)
                if not texto and not m.get("adjuntos"):
                    return self._json({"error": "el mensaje no puede quedar vacío"}, 400)
                m.setdefault("original", m["texto"])
                m["texto"], m["editado"] = texto, _ahora()
            elif u == "/api/edicion":                       # edición de un hallazgo: se guarda la versión, no se pisa
                key = str(d.get("key", ""))[:200]
                campos = {k: str(d.get(k, "")).strip()[:MAX_TEXTO] for k in ("tipo", "clausula", "justificacion")}
                if not key or not all(campos.values()):
                    return self._json({"error": "faltan el tipo, la cláusula o la justificación"}, 400)
                if user not in {m["n"] for m in _estado["equipo"]}:
                    return self._json({"error": "solo el equipo puede editar hallazgos"}, 403)
                _estado["ediciones"].setdefault(key, []).append({"user": user, "fecha": _ahora(), **campos})
            elif u == "/api/edicion/deshacer":              # vuelve al original (quita todas las ediciones)
                _estado["ediciones"].pop(str(d.get("key", "")), None)
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
            elif u == "/api/version/guardar":              # versión editada de un PDF: nunca pisa el original ni otra versión
                doc = str(d.get("doc", ""))[:120]
                pags = d.get("paginas") if isinstance(d.get("paginas"), dict) else {}
                pags = {str(int(k)): str(v)[:100_000] for k, v in list(pags.items())[:500]
                        if str(k).isdigit() and isinstance(v, str)}
                if not doc or not re.fullmatch(r"[\w.\-]+", doc) or not pags:
                    return self._json({"error": "no hay cambios que guardar"}, 400)
                lista = _estado.setdefault("versiones", {}).setdefault(doc, [])
                n = max((v["n"] for v in lista), default=0) + 1
                VERSIONES.mkdir(parents=True, exist_ok=True)
                (VERSIONES / f"{doc}_v{n}.json").write_text(json.dumps({"doc": doc, "n": n, "paginas": pags}, ensure_ascii=False),
                                                            encoding="utf-8")
                base = d.get("base") if isinstance(d.get("base"), int) else 0
                lista.append({"n": n, "user": user, "fecha": _ahora(), "nota": str(d.get("nota", "")).strip()[:300],
                              "nombre": str(d.get("nombre", "")).strip()[:60], "base": base,
                              "paginas": sorted(int(k) for k in pags)})
                extra = {"n": n}
            elif u == "/api/doc/prioridad":                # prioridad de un documento (por ahora la cambia cualquiera)
                doc, valor = str(d.get("doc", "")), d.get("prioridad")
                if not DOC_ID.fullmatch(doc) or valor not in PRIORIDADES:
                    return self._json({"error": "documento o prioridad no válidos"}, 400)
                _estado.setdefault("docs_meta", {}).setdefault(doc, {})["prioridad"] = {"valor": valor, "user": user, "fecha": _ahora()}
            elif u == "/api/doc/revisado":                 # un documento sin hallazgos también se puede dar por revisado
                doc = str(d.get("doc", ""))
                if not DOC_ID.fullmatch(doc):
                    return self._json({"error": "documento no válido"}, 400)
                meta = _estado.setdefault("docs_meta", {}).setdefault(doc, {})
                if d.get("revisado"):
                    meta["revisado"] = {"user": user, "fecha": _ahora()}
                else:
                    meta.pop("revisado", None)
            elif u == "/api/compartir":                    # compartir un documento: aviso en la campanita de cada persona
                doc = str(d.get("doc", ""))
                equipo = {m["n"] for m in _estado["equipo"]}
                para = sorted({str(p) for p in d.get("para", []) if str(p) in equipo and str(p) != user})
                if not DOC_ID.fullmatch(doc) or not para:
                    return self._json({"error": "elige al menos a una persona del equipo"}, 400)
                nota = str(d.get("nota", "")).strip()[:MAX_TEXTO]
                _estado.setdefault("compartidos", []).append({"doc": doc, "de": user, "para": para, "nota": nota, "fecha": _ahora()})
                for p in para:
                    _estado["avisos"].append({"para": p, "de": user, "key": f"compartir:{doc}", "fecha": _ahora(),
                                              "texto": nota or f"Te ha compartido {doc}", "leido": False, "mencion": True})
            elif u == "/api/cargado/guardar":              # confirma un documento cargado: familia y prioridad
                c = _estado.get("cargados", {}).get(str(d.get("id", "")))
                if not c or c["user"] != user:
                    return self._json({"error": "documento cargado no encontrado"}, 404)
                familia = str(d.get("familia", "")).strip()[:60]
                if not familia:
                    return self._json({"error": "elige la familia del documento"}, 400)
                c.update({"familia": familia, "prioridad": d.get("prioridad") if d.get("prioridad") in PRIORIDADES else "Media",
                          "titulo": str(d.get("titulo", c.get("titulo", ""))).strip()[:160] or c.get("titulo", ""),
                          "confirmado": True})
            elif u == "/api/cargado/borrar":               # cancelar la carga (solo quien lo cargó, y solo si no se confirmó)
                cid = str(d.get("id", ""))
                c = _estado.get("cargados", {}).get(cid)
                if not c or c["user"] != user or c.get("confirmado"):
                    return self._json({"error": "no se puede cancelar esa carga"}, 400)
                _estado["cargados"].pop(cid)
                _borrar_cargado(cid)
            elif u == "/api/sesion/cerrar":                # «Cerrar sesión»: deja de listarse en «Sesiones abiertas»
                sid = str(d.get("sid", ""))[:40]
                _sesiones.get(user, {}).pop(sid, None)
                _presencia.pop(user, None)
                ahora_t = time.time()
                for k in [k for k, t in _sid_cerrados.items() if ahora_t - t > 3600]:
                    _sid_cerrados.pop(k)
                if sid:
                    _sid_cerrados[sid] = ahora_t
                return self._json({"ok": True})
            elif u == "/api/chat/vaciar":                   # vacía el chat SOLO para este usuario; los demás lo siguen viendo
                c = _chat(str(d.get("id", "")))
                if not c or not _ve(user, c):
                    return self._json({"error": "chat no disponible"}, 400)
                ultimo = max((m.get("id", 0) for m in _estado["mensajes"] if m["canal"] == c["id"]), default=0)
                _estado.setdefault("vaciados", {}).setdefault(user, {})[c["id"]] = ultimo
                _estado["avisos"] = [a for a in _estado["avisos"] if not (a["para"] == user and a["key"] == f"chat:{c['id']}")]
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
