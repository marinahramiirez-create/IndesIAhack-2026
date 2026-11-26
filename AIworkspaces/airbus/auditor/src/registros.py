"""
Reglas por código para los REGISTROS OPERATIVOS (STD-SEC-001 §10, «Criterios de control operativo»).

Los registros son tablas: el LLM se pierde en ellas y no debe hacer cuentas. Aquí se leen columna a columna y se
aplican los criterios del estándar. Las reglas se eligen por las CABECERAS de cada tabla (no por el nombre del
documento) y los plazos se leen del STD-SEC-001 vigente en tiempo de ejecución, con valores por defecto si no se
encuentran. Así valen para cualquier registro con la misma estructura (también en el corpus oculto).

  RB1 Prueba de restauración «Satisfactoria» con tiempo real > RTO                 (§10.4)  Inconsistencia
  RB2 Prueba de restauración fallida sin acción correctiva                          (§10.4)  No cumple
  RB3 Más de N meses entre dos pruebas consecutivas del mismo sistema               (§7)     No cumple
  RB4 Última prueba del sistema con más de N meses en la fecha de corte             (§7)     No cumple
  RB5 Incidencia de copia corregida en más de N horas                               (§10.4)  No cumple
  RB6 Copia fallida que no se repitió                                               (§10.4)  No cumple
  RB7 Sistema sin copia fuera de línea o inmutable                                  (§10.4)  No cumple
  RB8 Copia fuera de línea con más de N días en la fecha de corte                   (§10.4)  No cumple
  RA1 Revisión de accesos firmada por alguien distinto del propietario del sistema  (§10.1)  No cumple
  RA2 Más accesos revocados que revisados en una revisión                           (§10.1)  Inconsistencia
  RF1 Persona con cuenta activa (registro de cuentas) que no figura en formación    (§10.1)  Cobertura faltante
"""
import re
import unicodedata
from datetime import datetime

import pymupdf

from src.modelo import Hallazgo

CONF = 0.9
SISTEMA = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
FECHA = re.compile(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?")
VACIO = {"", "—", "-", "–", "n/a", "ninguna", "ninguno", "no", "sin copia"}
_cache_tablas: dict[str, list[dict]] = {}


# ------------------------------------------------------------------ lectura de tablas
def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _celda(pag, bbox) -> str:
    """Texto de una celda ordenando los caracteres por posición (el PDF guarda los guiones aparte)."""
    if not bbox:
        return ""
    r = pymupdf.Rect(bbox)
    chars = []
    for b in pag.get_text("rawdict", clip=r)["blocks"]:
        for linea in b.get("lines", []):
            for s in linea["spans"]:
                for c in s["chars"]:
                    cr = pymupdf.Rect(c["bbox"])
                    if cr.intersects(r):
                        chars.append((round(cr.y1 / 3), cr.x0, c["c"]))
    chars.sort()
    return " ".join("".join(c for _, _, c in chars).split())


def tablas(doc) -> list[dict]:
    """Tablas de datos del documento con su número de «Tabla N»: [{n, titulo, cab, filas}].
    Las que continúan en la página siguiente (misma cabecera) se unen a la anterior."""
    if doc.ruta in _cache_tablas:
        return _cache_tablas[doc.ruta]
    titulos = list(doc.tablas)            # «Tabla N. …» en orden de aparición
    salida, i = [], 0
    try:
        pdf = pymupdf.open(doc.ruta)
        for pag in pdf:
            for tb in pag.find_tables().tables:
                filas = [[_celda(pag, c) for c in fila.cells] for fila in tb.rows]
                if len(filas) < 2 or len(filas[0]) < 3 or filas[0][0] in ("Rol", "Versión", "Documento"):
                    continue                                  # portada, historial, firmas
                cab = [_sin_acentos(c) for c in filas[0]]
                if salida and cab == salida[-1]["cab"]:
                    salida[-1]["filas"] += filas[1:]          # continuación
                    continue
                t = titulos[i] if i < len(titulos) else {"n": len(salida) + 1, "titulo": ""}
                i += 1
                salida.append({"n": t["n"], "titulo": t.get("titulo", ""), "cab": cab, "filas": filas[1:]})
    except Exception:
        salida = []
    _cache_tablas[doc.ruta] = salida
    return salida


def _col(cab: list[str], *claves) -> int | None:
    for j, c in enumerate(cab):
        if all(k in c for k in claves):
            return j
    return None


def _f(s: str) -> datetime | None:
    m = FECHA.search(s or "")
    if not m:
        return None
    return datetime.strptime(m.group(0), "%Y-%m-%d %H:%M" if " " in m.group(0) else "%Y-%m-%d")


def _num(s: str) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return float(m.group(0).replace(",", ".")) if m else None


def fecha_corte(doc) -> datetime | None:
    m = re.search(r"[Ff]echa de corte[^:\n]*:\s*(\d{4}-\d{2}-\d{2})", doc.texto)
    return datetime.strptime(m.group(1), "%Y-%m-%d") if m else None


# ------------------------------------------------------------------ parámetros del estándar vigente
def parametros(std) -> dict:
    """Plazos de STD-SEC-001 vigente; si no se encuentran, los valores de la versión 3.0."""
    t = " ".join((std.texto if std else "").split())
    p = {"prueba_meses": 6, "correccion_h": 24, "offline_dias": 7}
    if m := re.search(r"Prueba de restauraci[oó]n\s+Al menos cada (\d+) meses", t, re.I):
        p["prueba_meses"] = int(m.group(1))
    if m := re.search(r"fallida[^.]{0,80}m[aá]ximo de (\d+)\s*horas", t, re.I):
        p["correccion_h"] = int(m.group(1))
    if m := re.search(r"fuera de l[ií]nea o inmutable con una antig[uü]edad m[aá]xima de (\d+) d[ií]as", t, re.I):
        p["offline_dias"] = int(m.group(1))
    return p


# ------------------------------------------------------------------ reglas
def _h(doc, ubic, tipo, clausula, just, fila, regla):
    return Hallazgo(doc.codigo, ubic, tipo, clausula, just, evidencia=" ".join(fila), origen=f"regla {regla}",
                    confianza=CONF, fuente="STD-SEC-001 vigente §10")


def _copias(doc, t, p, corte, out):
    cab, n = t["cab"], t["n"]
    cs, cf = _col(cab, "sistema"), _col(cab, "fecha de la prueba")
    crto, creal, cres, cacc = _col(cab, "rto"), _col(cab, "tiempo real"), _col(cab, "resultado"), _col(cab, "accion")
    if None not in (cs, cf, cres):                                        # Tabla de pruebas de restauración
        max_dias = p["prueba_meses"] * 30.44
        por_sistema: dict[str, list] = {}
        for fila in t["filas"]:
            s, f = fila[cs], _f(fila[cf])
            if not SISTEMA.match(s) or not f:
                continue
            por_sistema.setdefault(s, []).append((f, fila))
            res = _sin_acentos(fila[cres])
            rto, real = (_num(fila[crto]) if crto is not None else None), (_num(fila[creal]) if creal is not None else None)
            ubic = f"Tabla {n}, {s} ({f:%Y-%m-%d})"
            if "satisf" in res and rto is not None and real is not None and real > rto:
                out.append(_h(doc, ubic, "Inconsistencia", "IS.I.OR.220",
                              f"Prueba marcada como satisfactoria con un tiempo real de {real:g} h frente a un RTO "
                              f"de {rto:g} h (STD-SEC-001 §10.4: solo es satisfactoria si no supera el RTO).", fila, "RB1"))
            if "fallid" in res and cacc is not None and _sin_acentos(fila[cacc]) in VACIO:
                out.append(_h(doc, ubic, "No cumple", "IS.I.OR.220",
                              "Prueba de restauración fallida sin acción correctiva registrada "
                              "(STD-SEC-001 §10.4).", fila, "RB2"))
        for s, pruebas in por_sistema.items():
            pruebas.sort(key=lambda x: x[0])
            for (fa, _), (fb, fila) in zip(pruebas, pruebas[1:]):
                d = (fb - fa).days
                if d > max_dias:
                    out.append(_h(doc, f"Tabla {n}, {s} ({fb:%Y-%m-%d})", "No cumple", "IS.I.OR.220",
                                  f"Transcurrieron {d} días entre dos pruebas de restauración consecutivas de {s}; "
                                  f"el máximo es de {p['prueba_meses']} meses.", fila, "RB3"))
            ult, fila = pruebas[-1]
            if corte and (corte - ult).days > max_dias:
                out.append(_h(doc, f"Tabla {n}, {s}", "No cumple", "IS.I.OR.220",
                              f"Última prueba de restauración de {s} el {ult:%Y-%m-%d}: {(corte - ult).days} días hasta "
                              f"la fecha de corte; el máximo es de {p['prueba_meses']} meses.", fila, "RB4"))
        return

    cs, cf, ccor, crep = _col(cab, "sistema"), _col(cab, "fecha"), _col(cab, "corregida"), _col(cab, "repetida")
    if None not in (cs, cf) and (ccor is not None or crep is not None):    # Tabla de incidencias de copia
        for fila in t["filas"]:
            s, f = fila[cs], _f(fila[cf])
            if not SISTEMA.match(s) or not f:
                continue
            ubic = f"Tabla {n}, {s} ({f:%Y-%m-%d %H:%M})" if f.hour or f.minute else f"Tabla {n}, {s} ({f:%Y-%m-%d})"
            fc = _f(fila[ccor]) if ccor is not None else None
            if fc and (fc - f).total_seconds() / 3600 > p["correccion_h"]:
                horas = (fc - f).total_seconds() / 3600
                plazo = f"{horas / 24:.0f} días" if horas >= 48 else f"{horas:.0f} horas"
                out.append(_h(doc, ubic, "No cumple", "IS.I.OR.220",
                              f"Incidencia de copia corregida {plazo} después; el máximo es de {p['correccion_h']} "
                              f"horas (STD-SEC-001 §10.4).", fila, "RB5"))
            if crep is not None and _sin_acentos(fila[crep]).startswith("no"):
                out.append(_h(doc, ubic, "No cumple", "IS.I.OR.220",
                              "La copia fallida no se repitió (STD-SEC-001 §10.4: la copia se repite).", fila, "RB6"))
        return

    cs, cu = _col(cab, "sistema"), _col(cab, "fuera de linea")
    if None not in (cs, cu):                                              # Tabla de copias fuera de línea
        for fila in t["filas"]:
            s = fila[cs]
            if not SISTEMA.match(s):
                continue
            f = _f(fila[cu])
            if not f and _sin_acentos(fila[cu]) in VACIO:
                out.append(_h(doc, f"Tabla {n}, {s}", "No cumple", "IS.I.OR.210",
                              f"{s} no tiene copia fuera de línea ni inmutable (STD-SEC-001 §10.4).", fila, "RB7"))
            elif f and corte and (corte - f).days > p["offline_dias"]:
                out.append(_h(doc, f"Tabla {n}, {s}", "No cumple", "IS.I.OR.210",
                              f"Última copia fuera de línea de {s} el {f:%Y-%m-%d}: {(corte - f).days} días de "
                              f"antigüedad en la fecha de corte; el máximo es de {p['offline_dias']} días.", fila, "RB8"))


def _revisiones(doc, t, out):
    cab, n = t["cab"], t["n"]
    cs, cp, cfir = _col(cab, "sistema"), _col(cab, "propietario"), _col(cab, "firmad")
    crev, crevis, crevoc = _col(cab, "revision"), _col(cab, "revisados"), _col(cab, "revocados")
    if None in (cs, cp, cfir, crev) or _col(cab, "revision anterior") == crev:
        crev = next((j for j, c in enumerate(cab) if c.startswith("revision") and "anterior" not in c), None)
    if None in (cs, cp, cfir, crev):
        return
    for fila in t["filas"]:
        s, f = fila[cs], _f(fila[crev])
        if not SISTEMA.match(s) or not f:
            continue
        ubic = f"Tabla {n}, {s} (revisión del {f:%Y-%m-%d})"
        if fila[cfir] and fila[cp] and _sin_acentos(fila[cfir]) != _sin_acentos(fila[cp]):
            out.append(_h(doc, ubic, "No cumple", "IS.I.OR.210",
                          f"La revisión de accesos de {s} la firma {fila[cfir]}, no el propietario del sistema "
                          f"({fila[cp]}).", fila, "RA1"))
        rv, rc = (_num(fila[crevis]) if crevis is not None else None), (_num(fila[crevoc]) if crevoc is not None else None)
        if rv is not None and rc is not None and rc > rv:
            out.append(_h(doc, ubic, "Inconsistencia", "IS.I.OR.245",
                          f"Se revocan {rc:g} accesos de solo {rv:g} revisados: el registro es incoherente.", fila, "RA2"))


def _cuentas_activas(docs) -> tuple[set[str], object | None]:
    """Personas (E-xxxx) con alguna cuenta activa en el registro de cuentas del corpus."""
    for d in docs:
        if "Fecha de corte" not in d.texto or "Cuenta" not in d.texto:
            continue
        for t in tablas(d):
            ce, cest = _col(t["cab"], "empleado"), _col(t["cab"], "estado")
            if _col(t["cab"], "cuenta") is None or ce is None or cest is None:
                continue
            activas = {f[ce] for f in t["filas"] if re.fullmatch(r"E-\d{3,5}", f[ce] or "") and "activ" in _sin_acentos(f[cest])}
            if activas:
                return activas, d
    return set(), None


def _personal(docs) -> set[str]:
    """Personas del registro maestro de personal (tabla con empleado, nombre y alta). Vacío si no lo hay."""
    for d in docs:
        if "Fecha de corte" not in d.texto:
            continue
        for t in tablas(d):
            ce = _col(t["cab"], "empleado")
            if ce is not None and _col(t["cab"], "nombre") is not None and _col(t["cab"], "alta") is not None \
                    and _col(t["cab"], "cuenta") is None:
                return {f[ce] for f in t["filas"] if re.fullmatch(r"E-\d{3,5}", f[ce] or "")}
    return set()


def _formacion(doc, t, docs, out) -> str:
    ce, cfi = _col(t["cab"], "empleado"), _col(t["cab"], "formacion")
    if ce is None or cfi is None:
        return ""
    en_formacion = {f[ce] for f in t["filas"]}
    otros = [d for d in docs if d is not doc]
    activas, d_cuentas = _cuentas_activas(otros)
    if not d_cuentas:
        return ""
    personal = _personal(otros)
    if personal:        # §10.1 habla de personas del registro maestro; las cuentas sin persona son otro defecto
        activas &= personal
    titulo = t["titulo"] or f"Tabla {t['n']}"
    for e in sorted(activas - en_formacion):
        out.append(Hallazgo(doc.codigo, f"Tabla {t['n']} (falta {e})", "Cobertura faltante", "IS.I.OR.240",
                            f"{e} tiene una cuenta activa en {d_cuentas.codigo} pero no figura en el registro de "
                            f"formación (STD-SEC-001 §10.1: toda persona con cuenta activa tiene formación vigente).",
                            evidencia=titulo, origen="regla RF1", confianza=CONF,
                            fuente=f"STD-SEC-001 vigente §10.1 · {d_cuentas.codigo}"))
    return d_cuentas.texto


# ------------------------------------------------------------------ punto de entrada
def revisar(doc, docs, std=None) -> tuple[list[Hallazgo], str]:
    """Hallazgos de las reglas de registros y el texto de otros documentos usados como evidencia cruzada."""
    if "Fecha de corte" not in doc.texto or not doc.tablas:
        return [], ""
    p, corte, out, extra = parametros(std), fecha_corte(doc), [], ""
    for t in tablas(doc):
        _copias(doc, t, p, corte, out)
        _revisiones(doc, t, out)
        if _col(t["cab"], "formacion") is not None:
            extra = _formacion(doc, t, docs, out) or extra
    return out, extra
