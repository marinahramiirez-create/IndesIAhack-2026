"""Utilidades compartidas por los detectores."""
import re

from nimbus.conocimiento import norm
from nimbus.modelos import Hallazgo, Requisito

RE_CLAU = re.compile(r"^IS\.I\.OR\.\d{3}$")


def sec(s: str) -> str:
    return f" (§{s})" if s else ""


def tabla_ref(t) -> str:
    return f"Tabla {t.numero}{sec(t.seccion)}"


def columna(t, *nombres) -> int | None:
    """Índice de la primera columna cuya cabecera contiene alguno de los nombres (sin tildes)."""
    cab = [norm(c) for c in t.cabecera]
    for n in nombres:
        for i, c in enumerate(cab):
            if norm(n) in c:
                return i
    return None


def requisitos_de(doc) -> list[Requisito]:
    """Requisitos en prosa + requisitos en tablas (ID | Requisito | Tipo | Cláusula | Verificación)."""
    reqs = list(doc.requisitos)
    for t in doc.tablas:
        ic, it, icl = columna(t, "id"), columna(t, "tipo"), columna(t, "clausula")
        ir, iv = columna(t, "requisito"), columna(t, "verificacion")
        if ic is None or icl is None or ir is None or ic == ir:
            continue
        for f in t.filas:
            if re.match(r"^[A-Z0-9]{2,4}-SEC-\d{3}$|^SEC-REQ-\d{3}$", f[ic]):
                reqs.append(Requisito(f[ic], f[ir], f[it] if it is not None else "", f[icl],
                                      f[iv] if iv is not None else "", t.seccion, t.pagina))
                reqs[-1].tabla = t.numero
    return reqs


def ubic_req(r: Requisito) -> str:
    t = getattr(r, "tabla", None)
    return f"Tabla {t}{sec(r.seccion)}, {r.id}" if t else f"{r.id}{sec(r.seccion)}"


def clausula_valida(c: str, defecto: str = "IS.I.OR.210") -> str:
    return c if RE_CLAU.match(c or "") else defecto


def hallazgo(doc, ubicacion, tipo, clausula, justificacion, detector, evidencia="", confianza=0.8, pagina=0):
    return Hallazgo(doc.codigo, ubicacion, tipo, clausula, justificacion, confianza, detector, evidencia, pagina)
