"""
Revisión EN EQUIPO y en vivo de la pantalla de hallazgos (sin instalar nada: solo la biblioteca estándar).

    .\\.venv\\Scripts\\python servidor.py            # después de generar_revision.py (solo este ordenador)
    .\\.venv\\Scripts\\python servidor.py --lan      # además, para los compañeros de la misma red

Sirve salidas/revision/ en http://localhost:8765. Por seguridad solo escucha en este ordenador; con --lan también
en http://<tu-IP>:8765 para los compañeros de la misma red (o de la misma red de Radmin VPN).

Protecciones de red (sección «Seguridad» de este archivo):
  - solo atiende peticiones dirigidas a sus propias direcciones (cabecera Host) y rechaza las que llegan desde
    otra web (cabecera Origin): una página ajena abierta en el navegador no puede hablar con este servidor;
  - el tipo de cada adjunto se decide mirando el archivo, no lo que declara quien lo sube; SVG, HTML y demás
    tipos activos nunca se muestran dentro del navegador: se descargan.

Guarda en salidas/colaboracion.json, compartido por todos:
  - decisiones (aprobar / rechazar con comentario), con quién y cuándo;
  - comentarios por hallazgo, con @menciones → avisos (la campanita);
  - presencia: quién está mirando cada hallazgo («Marina también está en este hallazgo»);
  - usuarios, roles y permisos por módulo (src/permisos.py), con escalamiento de documentos a un Dueño de Proceso;
  - chats de tres tipos:
      canal   público para todo el equipo; solo el administrador del equipo lo crea, renombra o borra;
      grupo   lo crea cualquiera y elige quién entra; su creador es administrador del grupo (renombra,
              añade o quita miembros, da o quita el rol de administrador del grupo);
      privado conversación entre dos personas; solo ellas la ven.
El servidor solo envía a cada persona los chats y mensajes que puede ver.
Sesiones: /api/login da un token y TODAS las demás rutas sacan el usuario de ese token (cabecera X-Sesion), nunca
del cuerpo de la petición; cada operación comprueba el permiso de su rol en el servidor. Aviso: el inicio de sesión
sigue siendo de prototipo (no comprueba contraseñas: basta el correo de alguien del equipo); en producción, Entra ID.
La página pregunta cada 2,5 s si hay novedades. Nada sale de este ordenador; no toca respuestas.csv.
"""
import argparse
import json
import re
import secrets
import socket
import threading
import time
import unicodedata
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from src import permisos as P
from src import api_v1 as A
from src import claves_api as CA

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

# ------------------------------------------------------------------ Seguridad
# Adjuntos: solo estos tipos se muestran dentro del navegador, y el tipo lo decide _tipo_real() mirando los primeros
# bytes del archivo. Todo lo demás (SVG, HTML, Office, ejecutables…) se guarda como «application/octet-stream» y
# solo se puede descargar: un SVG con <script> abierto en esta misma dirección podría actuar en nombre de quien lo abre.
TIPOS_EN_LINEA = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "application/pdf",
                            "text/plain", "video/mp4", "video/webm", "audio/mpeg", "audio/mp4", "audio/wav",
                            "audio/ogg", "audio/webm"})
TIPO_DESCARGA = "application/octet-stream"
# Valores de la cabecera Host que atiende el servidor (los rellena main()). Vacío = sin comprobar (solo en pruebas).
_HOSTS: set[str] = set()

# Equipo inicial (después se gestiona desde Configuración → Usuarios; se guarda en colaboracion.json).
# «rol» es el id de un rol de src/permisos.py (roles editables por el Admin).
EDITAR_MIN = 30           # minutos durante los que se puede editar un mensaje del chat (la página usa el mismo valor)
EQUIPO_INICIAL = [{"n": "Sergio", "c": "sergio@airbus.es", "rol": P.ADMIN},
                  {"n": "Marina", "c": "marina@airbus.es", "rol": "aprobador"},
                  {"n": "Nelson", "c": "nelson@airbus.es", "rol": "revisor"},
                  {"n": "Valentina", "c": "valentina@airbus.es", "rol": "revisor"},
                  {"n": "Daniela", "c": "daniela@airbus.es", "rol": "revisor"}]

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
_tokens: dict[str, str] = {}           # token de sesión → usuario (en memoria: al reiniciar el servidor, hay que volver a entrar)
_HALL: dict[str, list[str]] = {}       # documento → claves «documento|ubicación» de sus hallazgos (leído de index.html)
_DATOS: dict = {"res": [], "docs": {}, "metricas": None}   # hallazgos y documentos completos de index.html (Métricas)
SESION_S = 30 * 60                     # una sesión sin señales durante 30 min deja de listarse


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
    P.migrar(_estado)                     # roles por defecto y roles antiguos («Administrador»…) → ids actuales


def _cargar_documentos():
    """Documentos y hallazgos de la pantalla generada: el servidor los necesita para saber el estado de cada documento."""
    _HALL.clear()
    for linea in (WEB / "index.html").read_text(encoding="utf-8").splitlines():
        if linea.startswith("const D=") and linea.endswith(";"):
            d = json.loads(linea[len("const D="):-1])
            _DATOS.update(res=d.get("res", []), docs=d.get("docs", {}), metricas=d.get("metricas"))
            for doc in d.get("docs", {}):
                _HALL[doc] = []
            for r in d.get("res", []):
                _HALL.setdefault(r["documento"], []).append(f"{r['documento']}|{r['ubicacion']}")
            return
    print("aviso: no encuentro los datos en index.html; las reglas de edición por estado no podrán comprobarse")


def _todas_las_claves() -> set[str]:
    return {k for ks in _HALL.values() for k in ks}


def _editables(user: str) -> dict:
    """Para la pantalla: por cada documento escalado, si este usuario puede editarlo ahora y, si no, por qué."""
    return {doc: P.motivo_no_editar(_estado, user, doc, _HALL.get(doc, [])) for doc in _estado["escalados"]}


API_RITMO = (60, 60.0)                   # API externa: como mucho 60 peticiones cada 60 s por clave
_ritmo_api: dict[str, list[float]] = {}
_guardado_api = [0.0]                    # el uso de la API se guarda como mucho cada 30 s (no en cada petición)


def _guardar():
    _guardado_api[0] = time.time()
    tmp = DATOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(_estado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATOS)


def _usuarios() -> set[str]:
    u = {d.get("user", "") for d in _estado["dec"].values()} | {c["user"] for c in _estado["comentarios"]}
    u |= {m["user"] for m in _estado["mensajes"]} | {m["n"] for m in _estado["equipo"]}
    return {x for x in u | set(_presencia) if x}


def _usuario_de_token(token: str) -> str:
    """Usuario de la sesión, solo si sigue en el equipo (un usuario eliminado pierde sus sesiones)."""
    user = _tokens.get(token or "", "")
    if user and not P.miembro(_estado, user):
        _tokens.pop(token, None)
        return ""
    return user


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
        return P.es_admin(_estado, user)
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


def _docs_validos() -> set:
    """Documentos del corpus (los de index.html) y documentos cargados ya confirmados (por su clave)."""
    return set(_HALL) | {c["clave"] for c in _estado.get("cargados", {}).values() if c.get("confirmado") and c.get("clave")}


def _clave_cargado(c: dict, cid: str) -> str:
    """Identificador del documento cargado: su código o, si no tiene, el nombre del archivo. Si ya existe (por ejemplo,
    una copia de un documento del corpus), se le añade «.c» y el final de su id: «REG-BKP-2026.c00f0»."""
    base = re.sub(r"[^\w.\-]+", "_", c.get("codigo") or Path(c.get("archivo", "")).stem)[:100].strip("._") or "documento"
    ocupadas = _docs_validos()
    clave = base if base not in ocupadas else f"{base}.c{cid[-5:]}"
    return clave if clave not in ocupadas else f"UP-{cid}"


def _borrar_cargado(cid: str):
    """Quita los archivos de un documento cargado (original, contenido e imágenes/texto de sus páginas)."""
    import shutil
    if not re.fullmatch(r"[0-9a-f]+", cid):
        return
    shutil.rmtree(WEB / "cargados" / cid, ignore_errors=True)
    for f in (WEB / "paginas").glob(f"up_{cid}_*"):
        f.unlink(missing_ok=True)


def _tipo_real(datos: bytes, declarado: str) -> str:
    """Tipo del archivo según sus primeros bytes. Lo que declara quien lo sube solo sirve para desempatar
    (audio o vídeo en el mismo contenedor); nunca basta para que algo se muestre dentro del navegador."""
    c = datos[:16]
    audio = declarado.startswith("audio/")
    if c.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if c.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if c.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if c[:4] == b"RIFF" and c[8:12] == b"WEBP":
        return "image/webp"
    if c[:4] == b"RIFF" and c[8:12] == b"WAVE":
        return "audio/wav"
    if c.startswith(b"%PDF-"):
        return "application/pdf"
    if c[4:8] == b"ftyp":                              # contenedor MP4 / MOV / M4A / AVIF / HEIC
        marca = c[8:12]
        if marca in (b"avif", b"avis"):
            return "image/avif"
        if marca in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return TIPO_DESCARGA
        return "audio/mp4" if audio else "video/mp4"
    if c.startswith(b"\x1a\x45\xdf\xa3"):              # WebM / Matroska
        return "audio/webm" if audio else "video/webm"
    if c.startswith(b"OggS"):
        return "audio/ogg"
    if c.startswith(b"ID3") or (audio and len(c) > 1 and c[0] == 0xFF and (c[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if declarado == "text/plain" and b"\x00" not in datos:
        try:
            datos.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    return TIPO_DESCARGA


def _hosts_permitidos(puerto: int, lan: bool, extra: list[str]) -> set[str]:
    """Valores de Host válidos: este ordenador y, con --lan, sus IP y su nombre en la red."""
    nombres = {"localhost", "127.0.0.1", "[::1]"}
    if lan:
        nombres |= set(ips_locales()) | {socket.gethostname().lower()}
    hosts = set()
    for n in nombres:
        hosts.add(f"{n}:{puerto}")
        if puerto == 80:
            hosts.add(n)
    for e in extra:                                    # --host-permitido: tal cual y, si no trae puerto, también con él
        e = e.strip().lower()
        if e:
            hosts.add(e)
            if not re.search(r":\d+$", e):
                hosts.add(f"{e}:{puerto}")
    return hosts


class Manejador(SimpleHTTPRequestHandler):
    timeout = 60              # segundos sin recibir datos antes de soltar la conexión (evita hilos colgados)

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def log_message(self, *_):            # sin ruido en la consola
        pass

    def _origen_ok(self) -> bool:
        """Rechaza lo que no va dirigido a este servidor o llega desde otra web.
        - Host: solo las direcciones propias (_HOSTS). Corta el «DNS rebinding», con el que una web de fuera
          consigue que el navegador le hable a este servidor creyendo que es el suyo.
        - Origin (en los POST): el navegador la pone siempre que la petición sale de otra página; si no es una
          dirección propia, es otra web intentando actuar con el navegador de un compañero (CSRF).
        Los programas que no son navegadores (curl, scripts) no mandan Origin y pasan: no son este tipo de ataque."""
        if not _HOSTS:
            return True
        if self.headers.get("Host", "").strip().lower() not in _HOSTS:
            return False
        if self.command == "POST":
            origen = self.headers.get("Origin")
            if origen is not None:
                return urlparse(origen).netloc.lower() in _HOSTS
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return False
        return True

    def _rechazar_origen(self):
        self.close_connection = True
        return self._json({"error": "Dirección no permitida. Abre la app con una de las direcciones que muestra el "
                                    "servidor al arrancar (o arráncalo con --host-permitido NOMBRE)."}, 403)

    def do_HEAD(self):
        if not self._origen_ok():
            return self._rechazar_origen()
        return super().do_HEAD()

    def end_headers(self):
        # La página se regenera a menudo: que el navegador la pida siempre de nuevo (si no, enseña la versión antigua)
        if self.command == "GET" and urlparse(self.path).path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, datos, code=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _longitud(self, limite: int) -> int | None:
        """Content-Length si es válido (0..limite); si no, None y se cierra la conexión sin leer el cuerpo.
        Un valor negativo hacía que read() leyera hasta que el cliente quisiera: memoria sin límite."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > limite:
            self.close_connection = True
            return None
        return n

    def _cuerpo(self, limite: int = 20000) -> dict | None:
        """Cuerpo JSON de la petición (siempre un diccionario). None = tamaño no válido o por encima del límite."""
        n = self._longitud(limite)
        if n is None:
            return None
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
        return d if isinstance(d, dict) else {}

    def _adjunto(self, q):
        """Descarga o muestra un archivo del chat, solo si quien lo pide puede ver ese chat."""
        aid = (q.get("id") or [""])[0]
        with _lock:
            user = _usuario_de_token((q.get("s") or [""])[0])
            meta = _estado["adjuntos"].get(aid)
            c = _chat(meta["chat"]) if meta else None
            if not meta or not c or not user or not _ve(user, c):   # sin sesión no se sirve nada, tampoco de un canal público
                return self._json({"error": "archivo no disponible"}, 404)
        ruta = ADJUNTOS / meta["archivo"]
        if not ruta.exists():
            return self._json({"error": "archivo no encontrado"}, 404)
        datos = ruta.read_bytes()
        # Lista cerrada también al servir: protege de adjuntos antiguos guardados con el tipo que declaró quien los subió
        tipo = meta["tipo"] if meta["tipo"] in TIPOS_EN_LINEA else TIPO_DESCARGA
        en_linea = tipo != TIPO_DESCARGA and (q.get("descargar") or ["0"])[0] != "1"
        ascii_ = re.sub(r'[^\w.\- ]', "_", meta["nombre"], flags=re.ASCII) or "archivo"   # las cabeceras solo admiten latin-1
        self.send_response(200)
        self.send_header("Content-Type", tipo + ("; charset=utf-8" if tipo == "text/plain" else ""))
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Content-Disposition", f'{"inline" if en_linea else "attachment"}; filename="{ascii_}"; '
                                                f"filename*=UTF-8''{quote(meta['nombre'], safe='')}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")      # otras webs no pueden incrustarlo
        self.send_header("Referrer-Policy", "no-referrer")                   # la dirección lleva el token de sesión (?s=)
        if tipo != "application/pdf":      # (el visor de PDF del navegador no funciona dentro de un «sandbox»)
            # Si alguien abre el archivo directamente, se ve pero no puede ejecutar nada ni llamar a /api
            self.send_header("Content-Security-Policy",
                             "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(datos)

    def _subir(self):
        """Recibe un archivo (cuerpo binario) para adjuntarlo a un mensaje del chat."""
        from urllib.parse import unquote
        with _lock:
            user = _usuario_de_token(self.headers.get("X-Sesion", ""))
        chat = unquote(self.headers.get("X-Chat", ""))[:200]
        nombre = unquote(self.headers.get("X-Nombre", "archivo"))[:120] or "archivo"
        declarado = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()[:100]
        n = self._longitud(MAX_ADJUNTO)
        with _lock:
            c = _chat(chat)
            permitido = bool(user and c and _ve(user, c))
        if not permitido or not n:
            self.close_connection = True          # no se lee el cuerpo: se cierra la conexión
            if not permitido:
                return self._json({"error": "no puedes adjuntar en ese chat"}, 403)
            return self._json({"error": "el archivo está vacío o pasa de 25 MB"}, 400)
        datos = self.rfile.read(n)
        tipo = _tipo_real(datos, declarado)       # el tipo sale del contenido, no de lo que declara quien sube
        aid = secrets.token_hex(8)                # identificador imposible de adivinar y sin choques entre subidas
        ext = Path(nombre).suffix.lower()
        ext = ext if re.fullmatch(r"\.[a-z0-9]{1,9}", ext) else ""
        ADJUNTOS.mkdir(parents=True, exist_ok=True)
        (ADJUNTOS / f"{aid}{ext}").write_bytes(datos)
        with _lock:
            _estado["adjuntos"][aid] = {"nombre": nombre, "tipo": tipo, "tam": n, "chat": chat, "user": user,
                                        "fecha": _ahora(), "archivo": f"{aid}{ext}"}
            _guardar()
        return self._json({"ok": True, "id": aid, "nombre": nombre, "tipo": tipo, "tam": n})

    def _api_v1(self, u):
        """API externa de solo lectura (src/api_v1.py). Pide una clave de API personal, no la sesión de la página."""
        from datetime import date
        q = parse_qs(u.query)
        if u.path == "/api/v1/openapi.json":
            return self._json(A.OPENAPI)
        if u.path == "/api/v1/docs":
            cuerpo = A.pagina_docs("http://" + self.headers.get("Host", "localhost")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(cuerpo)
        auth = self.headers.get("Authorization", "")
        clave = auth[7:].strip() if auth[:7].lower() == "bearer " else self.headers.get("X-API-Key", "")
        alcance = A.alcance_de(u.path)
        ahora = datetime.now()
        with _lock:
            if not alcance:
                code, cuerpo, tipo = (*A.error(404, "no_encontrado", "Ruta desconocida. Mira /api/v1/docs."), "json")
                reg = None
            else:
                try:
                    reg = CA.verificar(_estado, clave, alcance, ahora)
                except P.Denegado as e:
                    CA.registrar_uso(_estado, None, u.path, e.code, ahora)
                    return self._json({"error": {"codigo": "no_autorizado" if e.code == 401 else "sin_permiso", "mensaje": str(e)}}, e.code)
                marcas = [t for t in _ritmo_api.get(reg["id"], []) if time.time() - t < API_RITMO[1]]
                if len(marcas) >= API_RITMO[0]:
                    espera = int(API_RITMO[1] - (time.time() - marcas[0])) + 1
                    _ritmo_api[reg["id"]] = marcas
                    CA.registrar_uso(_estado, reg, u.path, 429, ahora)
                    self.send_response(429)
                    cuerpo = json.dumps({"error": {"codigo": "demasiadas_peticiones",
                                                   "mensaje": f"Como mucho {API_RITMO[0]} peticiones por minuto: espera {espera} s."}},
                                        ensure_ascii=False).encode("utf-8")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Retry-After", str(espera))
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    return self.wfile.write(cuerpo)
                _ritmo_api[reg["id"]] = marcas + [time.time()]
                cargados = [c for c in _estado.get("cargados", {}).values() if c.get("confirmado")]
                code, cuerpo, tipo = A.responder(u.path, q, _DATOS["res"], _DATOS["docs"], _estado, cargados, date.today(), _DATOS["metricas"])
            CA.registrar_uso(_estado, reg, u.path, code, ahora)
            if time.time() - _guardado_api[0] > 30:
                _guardar()
        if tipo == "json":
            return self._json(cuerpo, code)
        datos = cuerpo.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'inline; filename="{u.path.rsplit("/", 1)[1]}.csv"')
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _metricas(self, q):
        """Resumen, cumplimiento, equipo (de conjunto) y calidad de la IA, con los filtros de la petición."""
        from datetime import date
        from src import metricas as M
        filtros = {k: (q.get(k) or [""])[0][:80] for k in ("familia", "prioridad", "tipo", "clausula", "periodo")}
        with _lock:
            user = _usuario_de_token(self.headers.get("X-Sesion", ""))
            if not user:
                return self._json({"error": "sesión no válida: vuelve a entrar"}, 401)
            if not P.puede(_estado, user, "metricas", "consultar"):
                return self._json({"error": "Tu rol no permite: Ver métricas."}, 403)
            cargados = [c for c in _estado.get("cargados", {}).values() if c.get("confirmado")]
            datos = M.calcular(_DATOS["res"], _DATOS["docs"], _estado, cargados, filtros, date.today(), _DATOS["metricas"])
        return self._json(datos)

    def _recibir_documento(self):
        """«Cargar archivo» en Auditorías: guarda el original y lo prepara para abrirlo en Revisión (src/cargados.py).
        Queda pendiente de confirmar (familia y prioridad) con /api/cargado/guardar. Usuario: el del token."""
        from urllib.parse import unquote
        with _lock:
            user = _usuario_de_token(self.headers.get("X-Sesion", ""))
            permitido = bool(user) and P.puede(_estado, user, "revisiones", "cargar")
        nombre = Path(unquote(self.headers.get("X-Nombre", "documento"))[:120]).name or "documento"
        n = self._longitud(MAX_ADJUNTO)           # None si el Content-Length es negativo, no numérico o pasa de 25 MB
        if not permitido or not n:
            self.close_connection = True          # no se lee el cuerpo: se cierra la conexión
            if not user:
                return self._json({"error": "sesión no válida: vuelve a entrar"}, 401)
            if not permitido:
                return self._json({"error": "Tu rol no permite: Cargar documentos."}, 403)
            return self._json({"error": "el archivo está vacío o pasa de 25 MB"}, 400)
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

    def _login(self, d):
        """Entrar con el correo (o el nombre) de alguien del equipo → token de sesión. Sin contraseña (prototipo)."""
        em = str(d.get("correo", "")).strip().lower()[:80]
        loc = re.split(r"[._\-\s]+", em.split("@")[0])[0] if em else ""
        with _lock:
            m = next((x for x in _estado["equipo"] if x["c"] == em), None) or \
                next((x for x in _estado["equipo"] if loc and _norm(x["n"]) == _norm(loc)), None)
            if not m:
                return self._json({"error": "Ese correo no está dado de alta. Pide a un administrador que te cree el usuario."}, 403)
            token = secrets.token_urlsafe(24)
            _tokens[token] = m["n"]
            return self._json({"ok": True, "token": token, "n": m["n"], "c": m["c"], "rol": m["rol"]})

    def do_GET(self):
        if not self._origen_ok():
            return self._rechazar_origen()
        u = urlparse(self.path)
        if u.path.startswith("/api/v1/"):
            return self._api_v1(u)
        if u.path == "/api/adjunto":
            return self._adjunto(parse_qs(u.query))
        if u.path == "/api/metricas":                 # pestaña Métricas: todas las cifras salen de src/metricas.py
            return self._metricas(parse_qs(u.query))
        if u.path == "/api/version":                  # texto completo de una versión (la lista va en /api/estado)
            with _lock:
                if not P.puede(_estado, _usuario_de_token(self.headers.get("X-Sesion", "")), "revisiones", "consultar"):
                    return self._json({"error": "Tu rol no permite consultar revisiones."}, 403)
            q = parse_qs(u.query)
            doc, n = (q.get("doc") or [""])[0], (q.get("n") or [""])[0]
            f = VERSIONES / f"{doc}_v{n}.json"
            if not re.fullmatch(r"[\w.\-]+", doc) or not n.isdigit() or not f.exists():
                return self._json({"error": "versión no encontrada"}, 404)
            return self._json(json.loads(f.read_text(encoding="utf-8")))
        if u.path != "/api/estado":
            return super().do_GET()
        q = parse_qs(u.query)
        key = (q.get("key") or [""])[0][:200]
        sid = (q.get("sid") or [""])[0][:40]
        with _lock:
            user = _usuario_de_token(self.headers.get("X-Sesion", ""))
            if not user:
                return self._json({"error": "sesión no válida: vuelve a entrar"}, 401)
            _presencia[user] = {"key": key, "t": time.time()}
            if user and sid:                  # «Mi cuenta → Sesiones abiertas»: cada pestaña del navegador es una sesión
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
            ve = P.puede(_estado, user, "revisiones", "consultar")     # sin permiso no se envían los datos de revisión
            ve_cfg = P.puede(_estado, user, "configuracion", "consultar")
            self._json({"seq": _estado["seq"], "user": user, "dec": _estado["dec"] if ve else {},
                        "comentarios": _estado["comentarios"] if ve else [],
                        "avisos": [a for a in _estado["avisos"] if a["para"] == user], "presencia": vivos,
                        "chats": chats, "mensajes": visibles[-800:],
                        "equipo": _estado["equipo"], "ediciones": _estado["ediciones"] if ve else {},
                        "versiones": _estado.get("versiones", {}) if ve else {}, "sesiones": mias,
                        "roles": _estado["roles"] if ve_cfg else [{"id": r["id"], "nombre": r["nombre"]} for r in _estado["roles"]],
                        "modulos": P.MODULOS, "permisos": P.permisos_de(_estado, user),
                        "escalados": _estado["escalados"] if ve else {},
                        "escalados_hist": _estado["escalados_hist"][-300:] if ve else [],
                        "editables": _editables(user), "config": _estado["config"],
                        "docs_meta": _estado.get("docs_meta", {}) if ve else {},
                        "compartidos": [x for x in _estado.get("compartidos", []) if ve and (user == x["de"] or user in x["para"])],
                        "cargados": [{"id": k, **v} for k, v in _estado.get("cargados", {}).items() if ve and v.get("confirmado")],
                        "claves_api": CA.listar(_estado, user, datetime.now()),
                        "reglas": _estado["reglas"] if ve_cfg or ve else []})

    def do_POST(self):
        if not self._origen_ok():
            return self._rechazar_origen()
        u = urlparse(self.path).path
        if u == "/api/subir":
            return self._subir()
        if u == "/api/cargar":
            return self._recibir_documento()
        # Solo JSON declarado como tal: un formulario o un fetch «simple» desde otra web no puede mandarlo sin que el
        # navegador pida permiso antes (preflight), y ese permiso aquí nunca se da.
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self.close_connection = True
            return self._json({"error": "se esperaba Content-Type: application/json"}, 415)
        d = self._cuerpo(MAX_VERSION if u == "/api/version/guardar" else 20000)
        if d is None:
            return self._json({"error": "petición demasiado grande o con un tamaño no válido"}, 413)
        if u == "/api/login":
            return self._login(d)
        with _lock:                                     # el usuario sale SIEMPRE del token, nunca del cuerpo
            user = _usuario_de_token(self.headers.get("X-Sesion", ""))
        if not user:
            return self._json({"error": "sesión no válida: vuelve a entrar"}, 401)
        if u == "/api/asistente":
            return self._asistente(d)
        extra = {}
        with _lock:
            try:
                return self._operar(u, d, user, extra)
            except P.Denegado as e:
                return self._json({"error": str(e)}, e.code)

    def _operar(self, u, d, user, extra):
        """Una operación de escritura, ya con el usuario autenticado y dentro del candado."""
        if True:
            if u == "/api/decision":
                dec = d.get("dec")
                if dec not in ("approved", "rejected"):
                    return self._json({"error": "decisión no válida"}, 400)
                P.exigir(_estado, user, "revisiones", "aprobar" if dec == "approved" else "rechazar")
                validas = _todas_las_claves()
                keys = [str(k)[:200] for k in d.get("keys", [])[:500]]
                if not keys or (validas and not set(keys) <= validas):
                    return self._json({"error": "hallazgo no válido"}, 400)
                for doc in {k.split("|")[0] for k in keys}:      # devuelto y sin corregir: no se decide
                    if P.bloqueo_decision(_estado, doc):
                        return self._json({"error": P.bloqueo_decision(_estado, doc)}, 403)
                for key in keys:                        # cambiar una decisión ya tomada exige también el permiso de la anterior
                    previa = _estado["dec"].get(key)
                    if previa and previa["dec"] != dec:
                        P.exigir(_estado, user, "revisiones", "aprobar" if previa["dec"] == "approved" else "rechazar")
                for key in keys:
                    _estado["dec"][key] = {"dec": dec, "note": str(d.get("note", ""))[:MAX_TEXTO], "user": user, "fecha": _ahora()}
            elif u == "/api/deshacer":
                previa = _estado["dec"].get(str(d.get("key", "")))
                if not previa:
                    return self._json({"error": "ese hallazgo no tiene decisión"}, 400)
                P.exigir(_estado, user, "revisiones", "aprobar" if previa["dec"] == "approved" else "rechazar")
                if P.bloqueo_decision(_estado, str(d.get("key", "")).split("|")[0]):
                    return self._json({"error": P.bloqueo_decision(_estado, str(d.get("key", "")).split("|")[0])}, 403)
                _estado["dec"].pop(str(d.get("key", "")), None)
            elif u == "/api/comentario":
                P.exigir(_estado, user, "revisiones", "comentar")
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
                    texto = "Adjunto: " + ", ".join(a["nombre"] for a in adj)
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
                P.exigir(_estado, user, "revisiones", "editar_hallazgos")
                key = str(d.get("key", ""))[:200]
                campos = {k: str(d.get(k, "")).strip()[:MAX_TEXTO] for k in ("tipo", "clausula", "justificacion")}
                if not key or not all(campos.values()):
                    return self._json({"error": "faltan el tipo, la cláusula o la justificación"}, 400)
                if _todas_las_claves() and key not in _todas_las_claves():
                    return self._json({"error": "hallazgo no válido"}, 400)
                _estado["ediciones"].setdefault(key, []).append({"user": user, "fecha": _ahora(), **campos})
            elif u == "/api/edicion/deshacer":              # vuelve al original (quita todas las ediciones)
                P.exigir(_estado, user, "revisiones", "editar_hallazgos")
                _estado["ediciones"].pop(str(d.get("key", "")), None)
            elif u == "/api/chat/crear":
                tipo = d.get("tipo")
                if tipo == "canal":
                    if not P.es_admin(_estado, user):
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
            elif u == "/api/equipo/alta":
                P.crear_usuario(_estado, user, d)
            elif u in ("/api/equipo/editar", "/api/equipo/rol"):
                P.editar_usuario(_estado, user, d)
            elif u == "/api/equipo/baja":
                n = str(d.get("n", ""))[:40]
                for doc in P.borrar_usuario(_estado, user, n, _ahora()):
                    _avisar_escalado(doc, user, "quitado")
                for t in [t for t, x in _tokens.items() if x == n]:   # sus sesiones dejan de valer
                    _tokens.pop(t)
            elif u == "/api/regla/crear":
                extra["id"] = P.crear_regla(_estado, user, d)
            elif u == "/api/regla/editar":
                P.editar_regla(_estado, user, d)
            elif u == "/api/regla/borrar":
                P.borrar_regla(_estado, user, str(d.get("id", "")))
            elif u == "/api/config/plazo":
                P.cambiar_plazo(_estado, user, d)
            elif u == "/api/rol/crear":
                extra["id"] = P.crear_rol(_estado, user, d)
            elif u == "/api/rol/editar":
                P.editar_rol(_estado, user, d)
            elif u == "/api/rol/borrar":
                P.borrar_rol(_estado, user, str(d.get("id", "")))
            elif u == "/api/escalar":
                doc = str(d.get("doc", ""))[:120]
                previo = (_estado["escalados"].get(doc) or {}).get("para")
                extra["accion"] = P.escalar(_estado, user, doc, str(d.get("para", ""))[:40], str(d.get("nota", "")),
                                            _ahora(), _docs_validos())
                _avisar_escalado(doc, user, "escalado", _estado["escalados"][doc]["para"])
                if previo:
                    _avisar_escalado(doc, user, "reasignado", previo)
            elif u == "/api/escalar/quitar":
                doc = str(d.get("doc", ""))[:120]
                para = (_estado["escalados"].get(doc) or {}).get("para")
                P.quitar_escalado(_estado, user, doc, _ahora())
                if para and para != user:
                    _avisar_escalado(doc, user, "quitado", para)
            elif u == "/api/version/guardar":              # versión editada de un PDF: nunca pisa el original ni otra versión
                doc = str(d.get("doc", ""))[:120]
                motivo = P.motivo_no_editar(_estado, user, doc, _HALL.get(doc, []))
                if motivo:                                  # escalado + a esta persona + Dueño de Proceso + estado editable
                    return self._json({"error": motivo}, 403)
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
                avisar = P.marcar_corregido(_estado, user, doc, n, _ahora())   # se desbloquean aprobar y rechazar
                if avisar and avisar != user:
                    _estado["avisos"].append({"para": avisar, "de": user, "key": f"{doc}|escalado", "fecha": _ahora(),
                                              "texto": f"{user} ha guardado los cambios de {doc} (v{n}): ya se puede decidir.",
                                              "leido": False})
            elif u == "/api/claves/crear":                 # clave de API personal: se devuelve en claro SOLO esta vez
                clave, pub = CA.crear(_estado, user, d.get("nombre"), d.get("dias"), d.get("alcances"), datetime.now())
                extra.update(clave=clave, registro=pub)
            elif u == "/api/claves/revocar":
                CA.revocar(_estado, user, str(d.get("id", "")), datetime.now())
            elif u == "/api/doc/prioridad":                # prioridad de un documento (permiso «Cambiar la prioridad»)
                P.exigir(_estado, user, "revisiones", "prioridad")
                doc, valor = str(d.get("doc", "")), d.get("prioridad")
                if doc not in _docs_validos() or valor not in PRIORIDADES:
                    return self._json({"error": "documento o prioridad no válidos"}, 400)
                _estado.setdefault("docs_meta", {}).setdefault(doc, {})["prioridad"] = {"valor": valor, "user": user, "fecha": _ahora()}
            elif u == "/api/doc/revisado":                 # un documento sin hallazgos también se puede dar por revisado
                P.exigir(_estado, user, "revisiones", "marcar_revisado")
                doc = str(d.get("doc", ""))
                if doc not in _docs_validos() or _HALL.get(doc):
                    return self._json({"error": "documento no válido"}, 400)
                meta = _estado.setdefault("docs_meta", {}).setdefault(doc, {})
                if d.get("revisado"):
                    meta["revisado"] = {"user": user, "fecha": _ahora()}
                else:
                    meta.pop("revisado", None)
            elif u == "/api/compartir":                    # compartir un documento: aviso en la campanita de cada persona
                P.exigir(_estado, user, "revisiones", "compartir")
                doc = str(d.get("doc", ""))
                equipo = {m["n"] for m in _estado["equipo"]}
                para = sorted({str(p) for p in d.get("para", []) if str(p) in equipo and str(p) != user})
                if doc not in _docs_validos() or not para:
                    return self._json({"error": "elige al menos a una persona del equipo"}, 400)
                nota = str(d.get("nota", "")).strip()[:MAX_TEXTO]
                _estado.setdefault("compartidos", []).append({"doc": doc, "de": user, "para": para, "nota": nota, "fecha": _ahora()})
                for p in para:
                    _estado["avisos"].append({"para": p, "de": user, "key": f"compartir:{doc}", "fecha": _ahora(),
                                              "texto": nota or f"Te ha compartido {doc}", "leido": False, "mencion": True})
            elif u == "/api/cargado/guardar":              # confirma un documento cargado: familia y prioridad
                P.exigir(_estado, user, "revisiones", "cargar")
                cid = str(d.get("id", ""))
                c = _estado.get("cargados", {}).get(cid)
                if not c or c["user"] != user:
                    return self._json({"error": "documento cargado no encontrado"}, 404)
                familia = str(d.get("familia", "")).strip()[:60]
                if not familia:
                    return self._json({"error": "elige la familia del documento"}, 400)
                c.update({"familia": familia, "prioridad": d.get("prioridad") if d.get("prioridad") in PRIORIDADES else "Media",
                          "titulo": str(d.get("titulo", c.get("titulo", ""))).strip()[:160] or c.get("titulo", ""),
                          "confirmado": True})
                c.setdefault("clave", _clave_cargado(c, cid))
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
                _tokens.pop(self.headers.get("X-Sesion", ""), None)   # el token de esta pestaña deja de valer
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


def _avisar_escalado(doc: str, de: str, que: str, para: str | None = None):
    """Aviso en la campanita del destinatario (o del anterior destinatario)."""
    para = para or (_estado["escalados"].get(doc) or {}).get("para")
    if not para or para == de:
        return
    textos = {"escalado": f"Te ha escalado {doc} para que lo corrijas.",
              "reasignado": f"{doc} ya no está escalado a ti: se ha asignado a otra persona.",
              "quitado": f"Se ha quitado el escalamiento de {doc}."}
    _estado["avisos"].append({"para": para, "de": de, "key": f"{doc}|escalado", "texto": textos[que],
                              "fecha": _ahora(), "leido": False})


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
    ap.add_argument("--lan", action="store_true",
                    help="aceptar también a los compañeros de la misma red (por defecto, solo este ordenador)")
    ap.add_argument("--host-permitido", action="append", default=[], metavar="NOMBRE[:PUERTO]",
                    help="otra dirección por la que se entra a la app (p. ej. detrás de un proxy); se puede repetir")
    a = ap.parse_args()
    if not (WEB / "index.html").exists():
        raise SystemExit("\nTodavía no está generada la pantalla.\n  → Ejecuta primero: .\\.venv\\Scripts\\python generar_revision.py\n")
    _cargar()
    _cargar_documentos()
    _HOSTS.update(_hosts_permitidos(a.puerto, a.lan, a.host_permitido))
    srv = ThreadingHTTPServer(("0.0.0.0" if a.lan else "127.0.0.1", a.puerto), Manejador)
    print("\nRevisión en equipo en marcha. Ábrela en el navegador:")
    print(f"  · En este ordenador:   http://localhost:{a.puerto}")
    if a.lan:
        for ip in ips_locales():
            print(f"  · Compañeros (misma red o Radmin VPN):  http://{ip}:{a.puerto}")
        print("\nAVISO: con --lan cualquiera de esa red puede llegar a la app, y el inicio de sesión es de prototipo")
        print("(no comprueba contraseñas). Úsalo solo en una red de confianza. Si cambias de red, vuelve a arrancar.")
        print("Si Windows pregunta por el Firewall, pulsa «Permitir».")
    else:
        print("\nSolo se puede abrir desde este ordenador. Para compartirla con los compañeros de la misma red:")
        print("  → python servidor.py --lan")
    print("Ctrl+C para pararla. Lo compartido se guarda en salidas\\colaboracion.json.\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Parada.")


if __name__ == "__main__":
    main()
