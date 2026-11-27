"""
Registro de actividad: quién hizo qué, cuándo y sobre qué documento. Lo usa servidor.py y se prueba en
tests/test_actividad.py.

Archivo: salidas/actividad.jsonl, una línea JSON por acción, que solo crece (nadie la edita ni la borra desde la app).
Cada línea lleva la huella de la anterior (cadena SHA-256): si alguien cambia, borra o inserta una línea a mano,
verificar() dice desde qué línea se rompió.

  {n, fecha, user, tipo, accion, doc, ref, detalle, prev, huella}

No se guarda el texto del chat ni de los comentarios; solo que hubo un comentario en un hallazgo.
"""
import copy
import csv
import hashlib
import io
import json
import threading
from pathlib import Path

GENESIS = "0" * 64
TIPOS = {"revision": "Revisión", "documentos": "Documentos", "escalados": "Escalados",
         "configuracion": "Configuración", "seguridad": "Seguridad"}
DEC = {"approved": "aceptado", "rejected": "rechazado"}


def _huella(e: dict) -> str:
    sin = {k: v for k, v in e.items() if k != "huella"}
    return hashlib.sha256(json.dumps(sin, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class Registro:
    """El archivo y una copia en memoria para filtrar rápido. Seguro entre hilos."""

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self._lock = threading.Lock()
        self.entradas: list[dict] = []
        self.cargar()

    def cargar(self):
        self.entradas = []
        if self.ruta.exists():
            for linea in self.ruta.read_text(encoding="utf-8").splitlines():
                try:
                    self.entradas.append(json.loads(linea))
                except ValueError:
                    pass                             # una línea rota la señala verificar(); aquí no se pierde el resto

    def anotar(self, user: str, ev: dict, fecha: str) -> dict:
        with self._lock:
            ult = self.entradas[-1] if self.entradas else None
            e = {"n": (ult["n"] + 1) if ult else 1, "fecha": fecha, "user": user, "tipo": ev["tipo"],
                 "accion": ev["accion"], "doc": ev.get("doc"), "ref": ev.get("ref"), "detalle": ev.get("detalle") or {},
                 "prev": ult["huella"] if ult else GENESIS}
            e["huella"] = _huella(e)
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            with self.ruta.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            self.entradas.append(e)
            return e

    def verificar(self) -> dict:
        """Relee el archivo del disco (no la copia en memoria) y comprueba la cadena."""
        if not self.ruta.exists():
            return {"ok": True, "total": 0, "linea": None, "motivo": ""}
        prev, total = GENESIS, 0
        for i, linea in enumerate(self.ruta.read_text(encoding="utf-8").splitlines(), 1):
            try:
                e = json.loads(linea)
            except ValueError:
                return {"ok": False, "total": total, "linea": i, "motivo": "la línea no se puede leer"}
            if e.get("n") != i:
                return {"ok": False, "total": total, "linea": i, "motivo": "falta o sobra una línea"}
            if e.get("prev") != prev:
                return {"ok": False, "total": total, "linea": i, "motivo": "no encaja con la línea anterior"}
            if e.get("huella") != _huella(e):
                return {"ok": False, "total": total, "linea": i, "motivo": "se ha modificado su contenido"}
            prev, total = e["huella"], total + 1
        return {"ok": True, "total": total, "linea": None, "motivo": ""}


# ------------------------------------------------------------------ qué se anota de cada operación

def _diff(a: dict | None, b: dict | None, campos=None) -> dict:
    a, b = a or {}, b or {}
    ks = campos or sorted(set(a) | set(b))
    antes = {k: a.get(k) for k in ks if a.get(k) != b.get(k)}
    despues = {k: b.get(k) for k in ks if a.get(k) != b.get(k)}
    return {"antes": antes, "despues": despues} if antes or despues else {}


def _plano(perm: dict) -> dict:
    return {f"{m}.{a}": v for m, accs in (perm or {}).items() if isinstance(accs, dict) for a, v in accs.items()}


def _rol(estado, rid):
    r = next((x for x in estado.get("roles", []) if x["id"] == rid), None)
    return r and {"nombre": r["nombre"], "descripcion": r.get("descripcion"), **_plano(r.get("permisos"))}


def _usuario(estado, n):
    m = next((x for x in estado.get("equipo", []) if x["n"] == n), None)
    return m and {"n": m["n"], "c": m["c"], "rol": m["rol"]}


def _regla(estado, rid):
    r = next((x for x in estado.get("reglas", []) if x["id"] == rid), None)
    return copy.deepcopy(r)


def _doc(k: str) -> str:
    return str(k).split("|")[0]


def antes(u: str, d: dict, estado: dict) -> dict:
    """Lo que hay antes de la operación, para poder anotar «antes → después»."""
    if u == "/api/decision":
        return {k: (estado["dec"].get(str(k)) or {}).get("dec") for k in d.get("keys", [])[:500]}
    if u == "/api/deshacer":
        return {"dec": (estado["dec"].get(str(d.get("key", ""))) or {}).get("dec")}
    if u in ("/api/edicion", "/api/edicion/deshacer"):
        ed = estado.get("ediciones", {}).get(str(d.get("key", ""))) or []
        return {"ultima": {k: ed[-1][k] for k in ("tipo", "clausula", "justificacion")} if ed else None, "n": len(ed)}
    if u == "/api/doc/prioridad":
        return {"valor": ((estado.get("docs_meta", {}).get(str(d.get("doc", ""))) or {}).get("prioridad") or {}).get("valor")}
    if u in ("/api/escalar", "/api/escalar/quitar"):
        return {"para": (estado["escalados"].get(str(d.get("doc", ""))) or {}).get("para")}
    if u in ("/api/equipo/editar", "/api/equipo/rol", "/api/equipo/baja"):
        return {"u": _usuario(estado, str(d.get("n", "")))}
    if u in ("/api/rol/editar", "/api/rol/borrar"):
        return {"r": _rol(estado, d.get("id"))}
    if u in ("/api/regla/editar", "/api/regla/borrar"):
        return {"r": _regla(estado, d.get("id"))}
    if u == "/api/config/plazo":
        return {"c": dict(estado.get("config", {}))}
    if u == "/api/claves/revocar":
        c = estado.get("claves_api", {}).get(str(d.get("id", "")))
        return {"c": c and {"nombre": c["nombre"], "prefijo": c["prefijo"], "user": c["user"]}}
    if u == "/api/cargado/guardar":
        c = estado.get("cargados", {}).get(str(d.get("id", "")))
        return {"c": c and {"archivo": c.get("archivo"), "confirmado": c.get("confirmado")}}
    if u == "/api/cargado/borrar":
        c = estado.get("cargados", {}).get(str(d.get("id", "")))
        return {"c": c and {"archivo": c.get("archivo")}}
    return {}


def evento(u: str, d: dict, antes_: dict, estado: dict, extra: dict) -> dict | list | None:
    """La operación ya se ha hecho bien → lo que se anota (o una lista, o None si no se registra)."""
    a = antes_ or {}
    if u == "/api/decision":
        dec = DEC.get(d.get("dec"))
        keys = [str(k) for k in d.get("keys", [])[:500]]
        por_doc: dict[str, list] = {}
        for k in keys:
            por_doc.setdefault(_doc(k), []).append(k)
        return [{"tipo": "revision", "accion": "decidir", "doc": doc,
                 "ref": ks[0] if len(ks) == 1 else None,
                 "detalle": {"decision": dec, "hallazgos": [k.split("|", 1)[-1] for k in ks],
                             "antes": sorted({DEC.get(a.get(k), "pendiente") for k in ks}),
                             **({"nota": str(d.get("note"))[:300]} if d.get("note") else {})}}
                for doc, ks in por_doc.items()]
    if u == "/api/deshacer":
        k = str(d.get("key", ""))
        return {"tipo": "revision", "accion": "deshacer", "doc": _doc(k), "ref": k, "detalle": {"antes": DEC.get(a.get("dec"))}}
    if u == "/api/comentario":
        k = str(d.get("key", ""))
        return {"tipo": "revision", "accion": "comentar", "doc": _doc(k), "ref": k}
    if u == "/api/edicion":
        k = str(d.get("key", ""))
        nuevo = {c: str(d.get(c, "")).strip()[:300] for c in ("tipo", "clausula", "justificacion")}
        return {"tipo": "revision", "accion": "editar_hallazgo", "doc": _doc(k), "ref": k,
                "detalle": _diff(a.get("ultima") or extra.get("_original"), nuevo) or {"despues": nuevo}}
    if u == "/api/edicion/deshacer":
        k = str(d.get("key", ""))
        return a.get("n") and {"tipo": "revision", "accion": "restaurar_hallazgo", "doc": _doc(k), "ref": k,
                               "detalle": {"ediciones": a["n"]}}
    if u == "/api/doc/prioridad":
        return {"tipo": "documentos", "accion": "prioridad", "doc": str(d.get("doc")),
                "detalle": {"antes": a.get("valor") or "Media", "despues": d.get("prioridad")}}
    if u == "/api/doc/revisado":
        return {"tipo": "documentos", "accion": "revisado" if d.get("revisado") else "no_revisado", "doc": str(d.get("doc"))}
    if u == "/api/compartir":
        c = (estado.get("compartidos") or [None])[-1]
        return {"tipo": "documentos", "accion": "compartir", "doc": str(d.get("doc")), "detalle": {"con": c["para"] if c else []}}
    if u == "/api/cargado/guardar":
        c = estado.get("cargados", {}).get(str(d.get("id", ""))) or {}
        if (a.get("c") or {}).get("confirmado"):
            return None
        return {"tipo": "documentos", "accion": "cargar", "doc": c.get("clave"),
                "detalle": {"archivo": c.get("archivo"), "familia": c.get("familia"), "prioridad": c.get("prioridad")}}
    if u == "/api/cargado/borrar":
        return {"tipo": "documentos", "accion": "cancelar_carga", "detalle": {"archivo": (a.get("c") or {}).get("archivo")}}
    if u == "/api/version/guardar":
        doc = str(d.get("doc", ""))
        v = (estado.get("versiones", {}).get(doc) or [{}])[-1]
        return {"tipo": "documentos", "accion": "version", "doc": doc,
                "detalle": {"version": v.get("n"), "paginas": v.get("paginas"), **({"nombre": v["nombre"]} if v.get("nombre") else {})}}
    if u == "/api/escalar":
        doc = str(d.get("doc", ""))
        para = (estado["escalados"].get(doc) or {}).get("para")
        return {"tipo": "escalados", "accion": "reasignar" if a.get("para") else "escalar", "doc": doc,
                "detalle": {"para": para, **({"antes": a["para"]} if a.get("para") else {})}}
    if u == "/api/escalar/quitar":
        return {"tipo": "escalados", "accion": "quitar_escalado", "doc": str(d.get("doc")), "detalle": {"antes": a.get("para")}}
    if u == "/api/equipo/alta":
        return {"tipo": "configuracion", "accion": "alta_usuario", "ref": str(d.get("n", ""))[:40],
                "detalle": {"despues": _usuario(estado, str(d.get("n", ""))[:40].strip())}}
    if u in ("/api/equipo/editar", "/api/equipo/rol"):
        n = str(d.get("n", ""))
        despues = _usuario(estado, n) or _usuario(estado, str(d.get("nuevo_n", "")))
        dif = _diff(a.get("u"), despues)
        return dif and {"tipo": "configuracion", "accion": "editar_usuario", "ref": n, "detalle": dif}
    if u == "/api/equipo/baja":
        return {"tipo": "configuracion", "accion": "baja_usuario", "ref": str(d.get("n", "")), "detalle": {"antes": a.get("u")}}
    if u == "/api/rol/crear":
        return {"tipo": "configuracion", "accion": "crear_rol", "ref": extra.get("id"), "detalle": {"despues": _rol(estado, extra.get("id"))}}
    if u == "/api/rol/editar":
        dif = _diff(a.get("r"), _rol(estado, d.get("id")))
        return dif and {"tipo": "configuracion", "accion": "editar_rol", "ref": str(d.get("id")),
                        "detalle": {"rol": (a.get("r") or {}).get("nombre"), **dif}}
    if u == "/api/rol/borrar":
        return {"tipo": "configuracion", "accion": "borrar_rol", "ref": str(d.get("id")), "detalle": {"antes": a.get("r")}}
    if u == "/api/regla/crear":
        return {"tipo": "configuracion", "accion": "crear_regla", "ref": extra.get("id"), "detalle": {"despues": _regla(estado, extra.get("id"))}}
    if u == "/api/regla/editar":
        dif = _diff(a.get("r"), _regla(estado, d.get("id")))
        return dif and {"tipo": "configuracion", "accion": "editar_regla", "ref": str(d.get("id")),
                        "detalle": {"regla": (a.get("r") or {}).get("nombre"), **dif}}
    if u == "/api/regla/borrar":
        return {"tipo": "configuracion", "accion": "borrar_regla", "ref": str(d.get("id")), "detalle": {"antes": a.get("r")}}
    if u == "/api/config/plazo":
        dif = _diff(a.get("c"), estado.get("config"), ["plazo_dias", "inicio"])
        return dif and {"tipo": "configuracion", "accion": "plazo", "detalle": dif}
    if u == "/api/claves/crear":
        r = extra.get("registro") or {}
        return {"tipo": "seguridad", "accion": "crear_clave", "ref": r.get("id"),
                "detalle": {"nombre": r.get("nombre"), "prefijo": r.get("prefijo"), "alcances": r.get("alcances"), "caduca": r.get("caduca")}}
    if u == "/api/claves/revocar":
        c = a.get("c") or {}
        return {"tipo": "seguridad", "accion": "revocar_clave", "ref": str(d.get("id")), "detalle": c}
    if u == "/api/login":
        return {"tipo": "seguridad", "accion": "entrar"}
    if u == "/api/sesion/cerrar":
        return {"tipo": "seguridad", "accion": "salir"}
    return None                                     # chat, avisos, «visto»…: no se registran


# ------------------------------------------------------------------ cómo se cuenta cada línea

def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, (list, tuple)):
        return ", ".join(map(str, v)) or "—"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _cambios(det: dict) -> str:
    a, b = det.get("antes") or {}, det.get("despues") or {}
    if not isinstance(a, dict) or not isinstance(b, dict):
        return ""
    ks = sorted(set(a) | set(b))
    return "; ".join(f"{k}: {_fmt(a.get(k))} → {_fmt(b.get(k))}" for k in ks[:12]) + (" …" if len(ks) > 12 else "")


def describir(e: dict) -> str:
    acc, det, doc, ref = e["accion"], e.get("detalle") or {}, e.get("doc") or "", e.get("ref") or ""
    ubic = ref.split("|", 1)[-1] if "|" in ref else ""
    h = det.get("hallazgos") or []
    textos = {
        "decidir": lambda: (f"{'Aceptó' if det.get('decision') == 'aceptado' else 'Rechazó'} "
                            + (f"el hallazgo {h[0]}" if len(h) == 1 else f"{len(h)} hallazgos") + f" de {doc}"),
        "deshacer": lambda: f"Deshizo la decisión ({det.get('antes') or '—'}) del hallazgo {ubic} de {doc}",
        "comentar": lambda: f"Comentó en el hallazgo {ubic} de {doc}",
        "editar_hallazgo": lambda: f"Editó el hallazgo {ubic} de {doc}",
        "restaurar_hallazgo": lambda: f"Volvió al original el hallazgo {ubic} de {doc}",
        "prioridad": lambda: f"Cambió la prioridad de {doc}: {det.get('antes')} → {det.get('despues')}",
        "revisado": lambda: f"Marcó {doc} como revisado",
        "no_revisado": lambda: f"Quitó la marca de revisado de {doc}",
        "compartir": lambda: f"Compartió {doc} con {_fmt(det.get('con'))}",
        "cargar": lambda: f"Cargó {det.get('archivo')} como {doc}",
        "cancelar_carga": lambda: f"Canceló la carga de {det.get('archivo')}",
        "version": lambda: f"Guardó la versión v{det.get('version')} de {doc}",
        "escalar": lambda: f"Escaló {doc} a {det.get('para')}",
        "reasignar": lambda: f"Reasignó {doc}: {det.get('antes')} → {det.get('para')}",
        "quitar_escalado": lambda: f"Quitó el escalamiento de {doc}" + (f" (era de {det['antes']})" if det.get("antes") else ""),
        "alta_usuario": lambda: f"Dio de alta a {ref}",
        "editar_usuario": lambda: f"Editó el usuario {ref}",
        "baja_usuario": lambda: f"Dio de baja a {ref}",
        "crear_rol": lambda: f"Creó el rol {(det.get('despues') or {}).get('nombre') or ref}",
        "editar_rol": lambda: f"Editó el rol {det.get('rol') or ref}",
        "borrar_rol": lambda: f"Eliminó el rol {(det.get('antes') or {}).get('nombre') or ref}",
        "crear_regla": lambda: f"Creó la regla {(det.get('despues') or {}).get('nombre') or ref}",
        "editar_regla": lambda: f"Editó la regla {det.get('regla') or ref}",
        "borrar_regla": lambda: f"Eliminó la regla {(det.get('antes') or {}).get('nombre') or ref}",
        "plazo": lambda: "Cambió el plazo de respuesta",
        "crear_clave": lambda: f"Creó la clave de API {det.get('nombre')} ({det.get('prefijo')}…)",
        "revocar_clave": lambda: f"Revocó la clave de API {det.get('nombre')} ({det.get('prefijo')}…)"
                                 + (f" de {det['user']}" if det.get("user") and det["user"] != e.get("user") else ""),
        "entrar": lambda: "Entró en la aplicación",
        "salir": lambda: "Cerró sesión",
    }
    return textos.get(acc, lambda: acc)()


def cambios_de(e: dict) -> str:
    det = e.get("detalle") or {}
    if e["accion"] in ("editar_hallazgo", "editar_usuario", "editar_rol", "editar_regla", "plazo"):
        return _cambios(det)
    if e["accion"] == "decidir" and det.get("nota"):
        return f"nota: {det['nota']}"
    return ""


def publica(e: dict) -> dict:
    return {k: e.get(k) for k in ("n", "fecha", "user", "tipo", "accion", "doc", "ref", "detalle")} \
        | {"texto": describir(e), "cambios": cambios_de(e)}


# ------------------------------------------------------------------ filtros, páginas y CSV

def filtrar(entradas: list[dict], q: dict) -> list[dict]:
    persona, tipo, doc = q.get("persona") or "", q.get("tipo") or "", q.get("doc") or ""
    desde, hasta, texto = q.get("desde") or "", q.get("hasta") or "", (q.get("q") or "").strip().lower()
    out = []
    for e in reversed(entradas):                     # lo más reciente primero
        if persona and e["user"] != persona:
            continue
        if tipo and e["tipo"] != tipo:
            continue
        if doc and e.get("doc") != doc:
            continue
        if desde and e["fecha"][:10] < desde:
            continue
        if hasta and e["fecha"][:10] > hasta:
            continue
        if texto and texto not in (describir(e) + " " + cambios_de(e) + " " + e["user"]).lower():
            continue
        out.append(e)
    return out


def pagina(lista: list[dict], pag, limite) -> dict:
    try:
        limite = max(1, min(500, int(limite or 100)))
        pag = max(1, int(pag or 1))
    except (TypeError, ValueError):
        limite, pag = 100, 1
    tot = len(lista)
    return {"datos": [publica(e) for e in lista[(pag - 1) * limite: pag * limite]], "total": tot, "pagina": pag,
            "limite": limite, "paginas": max(1, -(-tot // limite))}


def a_csv(lista: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["n", "fecha", "persona", "tipo", "accion", "documento", "descripcion", "cambios", "huella"])
    for e in lista:
        w.writerow([e["n"], e["fecha"], e["user"], TIPOS.get(e["tipo"], e["tipo"]), e["accion"], e.get("doc") or "",
                    describir(e), cambios_de(e), e["huella"]])
    return "﻿" + buf.getvalue()
