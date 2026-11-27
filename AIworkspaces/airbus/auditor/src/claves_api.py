"""
Claves de API personales (Mi cuenta → Claves de API). Lógica pura, sin HTTP: la usa servidor.py y se prueba en
tests/test_claves_api.py.

Modelo (en salidas/colaboracion.json):
  claves_api  {id: {id, user, nombre, prefijo, huella, alcances, creada, caduca, ultimo_uso, usos, revocada}}
  api_uso     [{fecha, clave, user, ruta, codigo}]            (las últimas 1000 peticiones)

Reglas:
  - La clave se enseña UNA vez al crearla. Solo se guarda su huella (SHA-256): ni el Admin puede volver a verla.
    Es aleatoria y larga (256 bits), así que la huella no se puede «adivinar» al revés.
  - Una clave actúa como su dueño: solo lee lo que permite su rol AHORA. Si la persona deja el equipo, pierde
    «Usar la API» o el permiso de lo que pide, la clave deja de valer en ese momento.
  - Siempre caduca (30, 90 o 365 días). Se puede revocar: su dueño o un Admin.
  - Alcances: métricas, documentos y hallazgos (solo lectura).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from src import permisos as P

PREFIJO = "nas_"                                   # Nimbus Audit Studio: así se reconoce en un escaneo de secretos
DIAS_VALIDOS = (30, 90, 365)
DIAS_POR_DEFECTO = 90
MAX_ACTIVAS = 10                                   # por persona
# alcance → (módulo, acción) que el rol necesita para leerlo
ALCANCES = {"metricas": ("metricas", "consultar"), "documentos": ("revisiones", "consultar"),
            "hallazgos": ("revisiones", "consultar")}


def _huella(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def estado_de(reg: dict, ahora: datetime) -> str:
    if reg.get("revocada"):
        return "revocada"
    return "caducada" if _ts(reg["caduca"]) <= ahora else "activa"


def publica(reg: dict, ahora: datetime) -> dict:
    """Lo que se puede enseñar de una clave (nunca la huella)."""
    return {k: reg.get(k) for k in ("id", "user", "nombre", "prefijo", "alcances", "creada", "caduca", "ultimo_uso", "usos", "revocada")} \
        | {"estado": estado_de(reg, ahora)}


def crear(estado: dict, user: str, nombre: str, dias, alcances, ahora: datetime) -> tuple[str, dict]:
    """Crea una clave. Devuelve (clave en claro — solo esta vez —, datos públicos)."""
    P.exigir(estado, user, "api", "usar")
    nombre = " ".join(str(nombre or "").split())[:60]
    if not nombre:
        raise P.Denegado("Pon un nombre a la clave (por ejemplo, «Power BI de calidad»).", 400)
    try:
        dias = int(dias or DIAS_POR_DEFECTO)
    except (TypeError, ValueError):
        dias = 0
    if dias not in DIAS_VALIDOS:
        raise P.Denegado("La caducidad tiene que ser de 30, 90 o 365 días.", 400)
    alc = sorted({str(a) for a in (alcances or [])})
    if not alc or any(a not in ALCANCES for a in alc):
        raise P.Denegado("Elige qué puede leer la clave: métricas, documentos o hallazgos.", 400)
    for a in alc:                                  # no se puede dar a una clave más de lo que permite tu rol
        m, acc = ALCANCES[a]
        if not P.puede(estado, user, m, acc):
            raise P.Denegado(f"Tu rol no permite leer «{a}»: la clave no puede tenerlo.")
    claves = estado.setdefault("claves_api", {})
    if sum(1 for c in claves.values() if c["user"] == user and estado_de(c, ahora) == "activa") >= MAX_ACTIVAS:
        raise P.Denegado(f"Ya tienes {MAX_ACTIVAS} claves activas: revoca alguna antes de crear otra.", 400)
    clave = PREFIJO + secrets.token_urlsafe(32)
    cid = secrets.token_hex(6)
    reg = {"id": cid, "user": user, "nombre": nombre, "prefijo": clave[:12], "huella": _huella(clave), "alcances": alc,
           "creada": ahora.isoformat(timespec="seconds"), "caduca": (ahora + timedelta(days=dias)).isoformat(timespec="seconds"),
           "ultimo_uso": None, "usos": 0, "revocada": None}
    claves[cid] = reg
    return clave, publica(reg, ahora)


def verificar(estado: dict, clave: str, alcance: str, ahora: datetime) -> dict:
    """La clave es válida para ese alcance → su registro. Si no, P.Denegado con 401 (quién eres) o 403 (qué puedes)."""
    clave = str(clave or "").strip()
    if not clave.startswith(PREFIJO):
        raise P.Denegado("Falta la clave de API (cabecera «Authorization: Bearer nas_…»).", 401)
    h = _huella(clave)
    reg = next((c for c in estado.get("claves_api", {}).values() if hmac.compare_digest(c["huella"], h)), None)
    if not reg:
        raise P.Denegado("Clave de API no válida.", 401)
    e = estado_de(reg, ahora)
    if e != "activa":
        raise P.Denegado(f"Esta clave de API está {e}.", 401)
    if not P.miembro(estado, reg["user"]):
        raise P.Denegado("El dueño de esta clave ya no está en el equipo.", 401)
    if not P.puede(estado, reg["user"], "api", "usar"):
        raise P.Denegado("El rol del dueño de esta clave ya no permite usar la API.")
    if alcance not in reg["alcances"]:
        raise P.Denegado(f"Esta clave no tiene el alcance «{alcance}».")
    m, acc = ALCANCES[alcance]
    if not P.puede(estado, reg["user"], m, acc):
        raise P.Denegado(f"El rol del dueño de esta clave ya no permite leer «{alcance}».")
    return reg


def registrar_uso(estado: dict, reg: dict | None, ruta: str, codigo: int, ahora: datetime) -> None:
    if reg:
        reg["ultimo_uso"], reg["usos"] = ahora.isoformat(timespec="seconds"), int(reg.get("usos") or 0) + 1
    uso = estado.setdefault("api_uso", [])
    uso.append({"fecha": ahora.isoformat(timespec="seconds"), "clave": reg["id"] if reg else None,
                "user": reg["user"] if reg else None, "ruta": ruta[:120], "codigo": codigo})
    del uso[:-1000]


def revocar(estado: dict, user: str, cid: str, ahora: datetime) -> None:
    reg = estado.get("claves_api", {}).get(str(cid))
    if not reg:
        raise P.Denegado("Esa clave no existe.", 404)
    if reg["user"] != user and not P.es_admin(estado, user):
        raise P.Denegado("Solo su dueño o un Admin puede revocar esta clave.")
    if not reg.get("revocada"):
        reg["revocada"] = {"por": user, "fecha": ahora.isoformat(timespec="seconds")}


def listar(estado: dict, user: str, ahora: datetime) -> list[dict]:
    """Las tuyas; un Admin ve las de todo el equipo. Más recientes primero."""
    admin = P.es_admin(estado, user)
    vis = [c for c in estado.get("claves_api", {}).values() if admin or c["user"] == user]
    return [publica(c, ahora) for c in sorted(vis, key=lambda c: c["creada"], reverse=True)]
