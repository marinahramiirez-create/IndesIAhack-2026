"""
Roles, permisos y escalamiento de la revisión en equipo (servidor.py). Lógica pura, sin HTTP: se prueba en
tests/test_permisos.py.

Modelo (se guarda en salidas/colaboracion.json):
  roles      [{id, nombre, descripcion, sistema, permisos: {modulo: {accion: bool}}}]
  equipo     [{n, c, rol: <id de rol>}]                 (rol obligatorio y siempre existente)
  escalados  {documento: {para, por, fecha, nota}}      (como mucho un escalamiento activo por documento)
  escalados_hist [{doc, accion, para, por, fecha, nota}] (registro: escalar, cambiar, quitar)

Reglas que no se pueden configurar (no son casillas de la matriz):
  - Solo el rol Admin crea, edita o elimina roles. Ningún permiso de otro rol lo concede.
  - Solo un Admin puede dar o quitar el rol Admin, y tiene que quedar al menos uno.
  - Editar un documento exige a la vez: que esté escalado, que el escalamiento sea a ESA persona, que su rol sea
    Dueño de Proceso con el permiso «Editar documentos escalados» y que el documento no esté Completado.
"""
import re
import unicodedata
from datetime import date

ADMIN = "admin"
DUENO = "dueno_proceso"
ROLES_SISTEMA = (ADMIN, DUENO)          # no se eliminan (las reglas de negocio dependen de ellos)

# Acciones REALES de la plataforma, por módulo: (id, nombre, descripción)
MODULOS = [
    ("revisiones", "Revisiones", [
        ("consultar", "Consultar revisiones", "Ver documentos, hallazgos, decisiones, comentarios y versiones"),
        ("aprobar", "Aprobar validaciones de IA", "Marcar hallazgos de la IA como aprobados (y deshacer esa decisión)"),
        ("rechazar", "Rechazar validaciones de IA", "Marcar hallazgos de la IA como rechazados (y deshacer esa decisión)"),
        ("comentar", "Comentar hallazgos", "Escribir en el debate de cada hallazgo, con @menciones"),
        ("editar_hallazgos", "Editar hallazgos de la IA", "Cambiar tipo, cláusula y justificación; el original se conserva"),
        ("escalar", "Escalar documentos", "Asignar un documento a un Dueño de Proceso, cambiar el destinatario o quitarlo"),
        ("editar_escalados", "Editar documentos escalados",
         "Crear versiones editadas de un documento. Solo el rol Dueño de Proceso y solo si el documento está escalado a esa persona"),
    ]),
    ("configuracion", "Configuración", [
        ("consultar", "Consultar configuración", "Ver reglas, criterio de aceptación, usuarios y roles"),
        ("editar_umbral", "Cambiar el umbral de aceptación", "El umbral se guarda en el navegador de cada persona"),
        ("editar_plazo", "Cambiar el plazo de respuesta",
         "Días disponibles para responder a la auditoría y fecha de inicio; se aplica a todo el equipo"),
        ("gestionar_usuarios", "Gestionar usuarios", "Crear, editar y eliminar usuarios (no puede dar ni quitar el rol Admin)"),
    ]),
    ("historico", "Descarga de histórico", [
        ("descargar_respuestas", "Descargar respuestas del auditor", "La salida oficial en CSV, Excel, JSON, Word o PDF"),
        ("descargar_revision", "Descargar revisión del equipo", "Decisiones, comentarios y ediciones del equipo"),
    ]),
]
ACCIONES = {m: [a for a, _, _ in acc] for m, _, acc in MODULOS}


def _todo(valor: bool) -> dict:
    return {m: {a: valor for a in acc} for m, acc in ACCIONES.items()}


def _perm(**por_modulo) -> dict:
    p = _todo(False)
    for m, acc in por_modulo.items():
        for a in acc:
            p[m][a] = True
    return p


_REV_COMUN = ["consultar", "aprobar", "rechazar", "comentar", "editar_hallazgos", "escalar"]
ROLES_INICIALES = [
    {"id": ADMIN, "nombre": "Admin", "sistema": True,
     "descripcion": "Administra la estructura de roles y el equipo; decide sobre los hallazgos.",
     "permisos": {**_todo(True), "revisiones": {**_todo(True)["revisiones"], "editar_escalados": False}}},
    {"id": "aprobador", "nombre": "Aprobador", "sistema": False,
     "descripcion": "Decide y firma las decisiones de los demás.",
     "permisos": _perm(revisiones=_REV_COMUN, configuracion=["consultar", "editar_umbral", "editar_plazo"],
                       historico=["descargar_respuestas", "descargar_revision"])},
    {"id": "revisor", "nombre": "Revisor", "sistema": False,
     "descripcion": "Aprueba o rechaza hallazgos y comenta.",
     "permisos": _perm(revisiones=_REV_COMUN, configuracion=["consultar", "editar_umbral"],
                       historico=["descargar_respuestas", "descargar_revision"])},
    {"id": DUENO, "nombre": "Dueño de Proceso", "sistema": True,
     "descripcion": "Corrige los documentos que se le escalan. No decide sobre los hallazgos.",
     "permisos": _perm(revisiones=["consultar", "comentar", "editar_escalados"], configuracion=["consultar"])},
]
# Roles de la versión anterior (nombre) → id actual
_ANTIGUOS = {"Administrador": ADMIN, "Admin": ADMIN, "Aprobador": "aprobador", "Revisor": "revisor",
             "Dueño de Proceso": DUENO}


PLAZO_DIAS = 15        # plazo de respuesta por defecto (Configuración → Reglas)


def cambiar_plazo(estado: dict, user: str, d: dict) -> None:
    """Plazo de respuesta (días) y fecha de inicio de la auditoría: los usa la columna «Días para responder»."""
    exigir(estado, user, "configuracion", "editar_plazo")
    cfg = dict(estado["config"])
    if "plazo_dias" in d:
        try:
            n = int(d.get("plazo_dias"))
        except (TypeError, ValueError):
            raise Denegado("El plazo tiene que ser un número de días.", 400)
        if not 1 <= n <= 365:
            raise Denegado("El plazo tiene que estar entre 1 y 365 días.", 400)
        cfg["plazo_dias"] = n
    if "inicio" in d:
        ini = str(d.get("inicio", ""))
        try:
            ini = date.fromisoformat(ini).isoformat()      # también rechaza fechas imposibles (2026-13-45)
        except ValueError:
            raise Denegado("La fecha de inicio no es válida.", 400)
        cfg["inicio"] = ini
    estado["config"] = cfg


class Denegado(Exception):
    """Operación no autorizada o no válida. code: 403 (permiso) o 400 (datos)."""

    def __init__(self, msg: str, code: int = 403):
        super().__init__(msg)
        self.code = code


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")


# ------------------------------------------------------------------ carga y migración
def migrar(estado: dict) -> None:
    """Asegura roles y que cada usuario tenga un rol existente (datos de versiones anteriores incluidos)."""
    if not estado.get("roles"):
        estado["roles"] = [dict(r, permisos={m: dict(a) for m, a in r["permisos"].items()}) for r in ROLES_INICIALES]
    ids = {r["id"] for r in estado["roles"]}
    for r in estado["roles"]:                      # acciones nuevas que no existían al guardar: desactivadas
        r["permisos"] = limpiar_permisos(r.get("permisos", {}), r["id"])
    for m in estado.get("equipo", []):
        if m.get("rol") not in ids:
            m["rol"] = _ANTIGUOS.get(m.get("rol"), "revisor" if "revisor" in ids else ADMIN)
    estado.setdefault("escalados", {})
    estado.setdefault("config", {})
    estado["config"].setdefault("plazo_dias", PLAZO_DIAS)
    estado["config"].setdefault("inicio", date.today().isoformat())   # inicio de la auditoría: editable en Reglas
    estado.setdefault("escalados_hist", [])


def limpiar_permisos(p, rol_id: str) -> dict:
    """Solo acciones conocidas y booleanas. Admin: fijo. «Editar documentos escalados» solo existe para Dueño de Proceso."""
    if rol_id == ADMIN:
        return next(dict((m, dict(a)) for m, a in r["permisos"].items()) for r in ROLES_INICIALES if r["id"] == ADMIN)
    p = p if isinstance(p, dict) else {}
    salida = {m: {a: (p.get(m) or {}).get(a) is True for a in acc} for m, acc in ACCIONES.items()}
    if rol_id != DUENO:
        salida["revisiones"]["editar_escalados"] = False
    return salida


# ------------------------------------------------------------------ consultas
def rol_de(estado: dict, user: str) -> dict | None:
    m = miembro(estado, user)
    return next((r for r in estado["roles"] if m and r["id"] == m["rol"]), None)


def miembro(estado: dict, user: str) -> dict | None:
    return next((m for m in estado["equipo"] if m["n"] == user), None)


def es_admin(estado: dict, user: str) -> bool:
    r = rol_de(estado, user)
    return bool(r and r["id"] == ADMIN)


def puede(estado: dict, user: str, modulo: str, accion: str) -> bool:
    """Sin usuario del equipo o sin rol, nada (no hay accesos por defecto)."""
    r = rol_de(estado, user)
    return bool(r and r["permisos"].get(modulo, {}).get(accion) is True)


def exigir(estado: dict, user: str, modulo: str, accion: str) -> None:
    if not puede(estado, user, modulo, accion):
        nombre = next(n for m, _, acc in MODULOS if m == modulo for a, n, _ in acc if a == accion)
        raise Denegado(f"Tu rol no permite: {nombre}.")


def permisos_de(estado: dict, user: str) -> dict:
    r = rol_de(estado, user)
    return {**(r["permisos"] if r else _todo(False)), "admin_roles": bool(r and r["id"] == ADMIN)}


def estado_doc(hallazgos: list[str], dec: dict) -> str:
    """Igual que estadoDoc() de la página: hallazgos = claves «documento|ubicación» de ese documento."""
    pend = sum(1 for k in hallazgos if k not in dec)
    return "Sin hallazgos" if not hallazgos else "Completado" if pend == 0 else "Pendiente" if pend == len(hallazgos) else "En revisión"


ESTADOS_EDITABLES = ("Pendiente", "En revisión", "Sin hallazgos")    # Completado: la revisión está cerrada


def motivo_no_editar(estado: dict, user: str, doc: str, hallazgos: list[str]) -> str | None:
    """None si puede editar el documento; si no, el motivo. Comprueba las cuatro condiciones a la vez."""
    esc = estado["escalados"].get(doc)
    r = rol_de(estado, user)
    if not esc:
        return "El documento no está escalado. Solo se edita cuando se escala a un Dueño de Proceso."
    if esc["para"] != user:
        return f"El documento está escalado a {esc['para']}: solo esa persona puede editarlo."
    if not r or r["id"] != DUENO:
        return "Solo puede editar quien tiene el rol Dueño de Proceso."
    if not puede(estado, user, "revisiones", "editar_escalados"):
        return "Tu rol no tiene activado «Editar documentos escalados»."
    e = estado_doc(hallazgos, estado.get("dec", {}))
    if e not in ESTADOS_EDITABLES:
        return f"El documento está «{e}»: su revisión está cerrada y ya no se edita."
    return None


# ------------------------------------------------------------------ roles (solo Admin)
def _texto(v, n: int) -> str:
    return str(v or "").strip()[:n]


def _id_rol(nombre: str, usados: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", _norm(nombre)).strip("_")[:30] or "rol"
    rid, i = base, 2
    while rid in usados:
        rid, i = f"{base}_{i}", i + 1
    return rid


def crear_rol(estado: dict, user: str, d: dict) -> str:
    if not es_admin(estado, user):
        raise Denegado("Solo el rol Admin puede crear roles.")
    nombre = _texto(d.get("nombre"), 40)
    if not nombre:
        raise Denegado("El rol necesita un nombre.", 400)
    if any(_norm(r["nombre"]) == _norm(nombre) for r in estado["roles"]):
        raise Denegado("Ya existe un rol con ese nombre.", 400)
    rid = _id_rol(nombre, {r["id"] for r in estado["roles"]})
    estado["roles"].append({"id": rid, "nombre": nombre, "descripcion": _texto(d.get("descripcion"), 300),
                            "sistema": False, "permisos": limpiar_permisos(d.get("permisos"), rid)})
    return rid


def editar_rol(estado: dict, user: str, d: dict) -> None:
    if not es_admin(estado, user):
        raise Denegado("Solo el rol Admin puede editar roles.")
    r = next((x for x in estado["roles"] if x["id"] == d.get("id")), None)
    if not r:
        raise Denegado("Ese rol no existe.", 400)
    if r["id"] == ADMIN:
        raise Denegado("El rol Admin no se modifica: tiene siempre todos los permisos de administración.", 400)
    if "nombre" in d and r["id"] != DUENO:            # Dueño de Proceso conserva su nombre (lo usa la regla de edición)
        nombre = _texto(d.get("nombre"), 40)
        if not nombre:
            raise Denegado("El rol necesita un nombre.", 400)
        if any(x is not r and _norm(x["nombre"]) == _norm(nombre) for x in estado["roles"]):
            raise Denegado("Ya existe un rol con ese nombre.", 400)
        r["nombre"] = nombre
    if "descripcion" in d:
        r["descripcion"] = _texto(d.get("descripcion"), 300)
    if "permisos" in d:
        r["permisos"] = limpiar_permisos(d.get("permisos"), r["id"])


def borrar_rol(estado: dict, user: str, rid: str) -> None:
    if not es_admin(estado, user):
        raise Denegado("Solo el rol Admin puede eliminar roles.")
    r = next((x for x in estado["roles"] if x["id"] == rid), None)
    if not r:
        raise Denegado("Ese rol no existe.", 400)
    if r["id"] in ROLES_SISTEMA:
        raise Denegado(f"El rol {r['nombre']} es del sistema y no se puede eliminar.", 400)
    usan = [m["n"] for m in estado["equipo"] if m["rol"] == rid]
    if usan:
        raise Denegado(f"No se puede eliminar: lo tienen {len(usan)} usuario(s) ({', '.join(usan[:5])}). "
                       "Cámbiales antes el rol.", 400)
    estado["roles"] = [x for x in estado["roles"] if x["id"] != rid]


# ------------------------------------------------------------------ usuarios
def _admins(estado: dict) -> list[str]:
    return [m["n"] for m in estado["equipo"] if m["rol"] == ADMIN]


def _comprobar_rol_asignable(estado: dict, user: str, rid, anterior: str | None = None) -> str:
    if not estado["roles"]:
        raise Denegado("Todavía no hay roles: crea uno antes de dar de alta usuarios.", 400)
    if not rid:
        raise Denegado("Todo usuario necesita un rol.", 400)
    if rid not in {r["id"] for r in estado["roles"]}:
        raise Denegado("Ese rol no existe.", 400)
    if ADMIN in (rid, anterior) and rid != anterior and not es_admin(estado, user):
        raise Denegado("Solo un Admin puede dar o quitar el rol Admin.")
    return rid


def crear_usuario(estado: dict, user: str, d: dict) -> None:
    exigir(estado, user, "configuracion", "gestionar_usuarios")
    n, c = _texto(d.get("n"), 40), _texto(d.get("c"), 80).lower()
    rid = _comprobar_rol_asignable(estado, user, d.get("rol"))
    if not n or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c):
        raise Denegado("Faltan el nombre o un correo válido.", 400)
    if any(_norm(m["n"]) == _norm(n) or m["c"] == c for m in estado["equipo"]):
        raise Denegado("Ya hay alguien con ese nombre o correo.", 400)
    estado["equipo"].append({"n": n, "c": c, "rol": rid})


def editar_usuario(estado: dict, user: str, d: dict) -> None:
    """Edita correo y rol. El nombre no cambia: identifica a la persona en decisiones, chats y escalamientos."""
    exigir(estado, user, "configuracion", "gestionar_usuarios")
    m = miembro(estado, str(d.get("n", "")))
    if not m:
        raise Denegado("Ese usuario no existe.", 400)
    if m["rol"] == ADMIN and not es_admin(estado, user):
        raise Denegado("Solo un Admin puede modificar a otro Admin.")
    c, rid = m["c"], m["rol"]                # primero se valida todo; solo después se aplica (nada a medias)
    if "c" in d:
        c = _texto(d.get("c"), 80).lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c):
            raise Denegado("Correo no válido.", 400)
        if any(x is not m and x["c"] == c for x in estado["equipo"]):
            raise Denegado("Ya hay alguien con ese correo.", 400)
    if "rol" in d and d.get("rol") != m["rol"]:
        if m["n"] == user and not es_admin(estado, user):
            raise Denegado("No puedes cambiar tu propio rol.")
        rid = _comprobar_rol_asignable(estado, user, d.get("rol"), m["rol"])
        if m["rol"] == ADMIN and _admins(estado) == [m["n"]]:
            raise Denegado("Tiene que quedar al menos un Admin.", 400)
    m["c"], m["rol"] = c, rid                # los permisos efectivos se calculan siempre desde el rol actual


def borrar_usuario(estado: dict, user: str, n: str, fecha: str) -> list[str]:
    """Elimina (convención existente: baja). Sus escalamientos activos se quitan y quedan en el registro."""
    exigir(estado, user, "configuracion", "gestionar_usuarios")
    m = miembro(estado, n)
    if not m:
        raise Denegado("Ese usuario no existe.", 400)
    if n == user:
        raise Denegado("No puedes eliminarte a ti mismo.", 400)
    if m["rol"] == ADMIN and not es_admin(estado, user):
        raise Denegado("Solo un Admin puede eliminar a otro Admin.")
    if m["rol"] == ADMIN and _admins(estado) == [n]:
        raise Denegado("Tiene que quedar al menos un Admin.", 400)
    quitados = [doc for doc, e in estado["escalados"].items() if e["para"] == n]
    for doc in quitados:
        _registrar(estado, doc, "quitar", estado["escalados"].pop(doc)["para"], user, fecha, "usuario eliminado")
    estado["equipo"] = [x for x in estado["equipo"] if x["n"] != n]
    return quitados


# ------------------------------------------------------------------ escalamiento
def _registrar(estado, doc, accion, para, por, fecha, nota=""):
    estado["escalados_hist"].append({"doc": doc, "accion": accion, "para": para, "por": por, "fecha": fecha, "nota": nota})
    del estado["escalados_hist"][:-2000]


def escalar(estado: dict, user: str, doc: str, para: str, nota: str, fecha: str, docs: set) -> str:
    """Escala (o cambia el destinatario). Devuelve «escalar» o «cambiar»."""
    exigir(estado, user, "revisiones", "escalar")
    if doc not in docs:
        raise Denegado("Ese documento no existe.", 400)
    destino = miembro(estado, para)
    if not destino or destino["rol"] != DUENO:
        raise Denegado("Solo se puede escalar a una persona con el rol Dueño de Proceso.", 400)
    previo = estado["escalados"].get(doc)
    if previo and previo["para"] == para:
        raise Denegado(f"Ya está escalado a {para}.", 400)
    estado["escalados"][doc] = {"para": para, "por": user, "fecha": fecha, "nota": _texto(nota, 300)}
    accion = "cambiar" if previo else "escalar"
    _registrar(estado, doc, accion, para, user, fecha, _texto(nota, 300))
    return accion


def bloqueo_decision(estado: dict, doc: str) -> str | None:
    """Escalado y sin corregir: nadie aprueba ni rechaza hasta que el destinatario guarde sus cambios."""
    e = estado["escalados"].get(doc)
    if e and not e.get("corregido"):
        return (f"El documento está devuelto a {e['para']} para que lo corrija: aprobar y rechazar se activan "
                "cuando guarde los cambios.")
    return None


def marcar_corregido(estado: dict, user: str, doc: str, version: int, fecha: str) -> str | None:
    """El destinatario ha guardado una versión: se desbloquean las decisiones. Devuelve a quién avisar."""
    e = estado["escalados"].get(doc)
    if not e or e["para"] != user:
        return None
    e["corregido"] = {"fecha": fecha, "version": version}
    _registrar(estado, doc, "corregir", user, user, fecha, f"v{version}")
    return e["por"]


def quitar_escalado(estado: dict, user: str, doc: str, fecha: str) -> None:
    """Lo quita quien puede escalar o el propio destinatario (al terminar su corrección)."""
    e = estado["escalados"].get(doc)
    if not e:
        raise Denegado("El documento no está escalado.", 400)
    if not (puede(estado, user, "revisiones", "escalar") or e["para"] == user):
        raise Denegado("Solo quien puede escalar o el destinatario pueden quitar el escalamiento.")
    estado["escalados"].pop(doc)
    _registrar(estado, doc, "quitar", e["para"], user, fecha)
