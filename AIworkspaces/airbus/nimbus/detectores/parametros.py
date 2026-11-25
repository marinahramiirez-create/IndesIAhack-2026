"""
Detectores de parámetros: los valores del documento se comparan CON CÓDIGO contra el estándar vigente y
contra los plazos de Part-IS (nunca los «lee» un LLM).

  tablas_de_parametros            tablas «Parámetro | Valor | (Requisito)» de cualquier documento.
  requisitos_frente_al_estandar   requisitos en prosa con un plazo/periodo que corresponde a un parámetro.

Sentido de la regla (lo da el propio estándar): «Máximo X» → el documento no puede superar X;
«Al menos cada X» → el intervalo del documento no puede ser mayor; «Al menos X» → no puede ser menor.
Un documento MÁS exigente que el estándar es conforme y no se marca.
"""
import re

from nimbus.conocimiento import duraciones_h, fichas, multiples, norm
from nimbus.detectores.comun import clausula_valida, columna, hallazgo, requisitos_de, sec, tabla_ref

CLAUSULA_POR_TEMA = [("conservaci", "IS.I.OR.245"), ("notificaci", "IS.I.OR.230"), ("evaluacion de riesgos", "IS.I.OR.205"),
                     ("formacion", "IS.I.OR.240"), ("competencia", "IS.I.OR.240"), ("proveedor", "IS.I.OR.235"),
                     ("auditoria interna", "IS.I.OR.260"), ("revision por la direccion", "IS.I.OR.260")]


def _valor_doc(valor: str, p) -> tuple[float | None, str]:
    if p.horas is not None:
        d = duraciones_h(valor)
        return (d[0][0], d[0][1]) if d else (None, "")
    if p.numero is not None:
        m = re.search(r"TLS\s*(\d\.\d)", valor) if "TLS" in p.valor else re.search(r"(\d+(?:[.,]\d+)?)", valor)
        return (float(m.group(1).replace(",", ".")), m.group(0)) if m else (None, "")
    return None, ""


def incumple(p, v: float) -> bool:
    ref = p.horas if p.horas is not None else p.numero
    if ref is None or v is None:
        return False
    if p.sentido in ("max", "periodo"):
        return v > ref * 1.001
    if p.sentido == "min":
        return v < ref * 0.999
    return False


def _clausula(doc, req_id: str, p, k) -> str:
    r = next((r for r in requisitos_de(doc) if r.id == req_id), None)
    if r and r.clausula.startswith("IS.I.OR"):
        return r.clausula
    m = re.search(r"IS\.I\.OR\.\d{3}", p.origen)
    if m:
        return m.group(0)
    n = norm(p.nombre)
    return next((c for clave, c in CLAUSULA_POR_TEMA if clave in n), "IS.I.OR.210")


def _fuente(p) -> str:
    return f"Part-IS ({p.origen.replace('Part-IS ', '')}): «{p.valor}»" if p.tabla == "Part-IS" \
        else f"el estándar vigente STD-SEC-001 (Tabla {p.tabla}) exige «{p.valor}»"


def tablas_de_parametros(doc, k):
    if doc.codigo.startswith("STD-SEC") or not k.parametros:
        return []
    salida = []
    for t in doc.tablas:
        ip, iv = columna(t, "parametro"), columna(t, "valor")
        if ip is None or iv is None:
            continue
        ir = columna(t, "requisito")
        for f in t.filas:
            req_id = f[ir] if ir is not None else ""
            for nombre, valor in multiples(f[ip], f[iv]):
                p = k.parametro(nombre)
                if not p:
                    continue
                v, txt = _valor_doc(valor, p)
                if incumple(p, v):
                    donde = f"{tabla_ref(t)}, {req_id}" if re.match(r"^[A-Z0-9-]+-\d{3}$", req_id) else f"{tabla_ref(t)}, «{f[ip]}»"
                    salida.append(hallazgo(doc, donde, "No cumple", _clausula(doc, req_id, p, k),
                                           f"{nombre}: {valor} en el documento; {_fuente(p)}.",
                                           "parametros.tablas", evidencia=" | ".join(f), confianza=0.9, pagina=t.pagina))
    return salida


def requisitos_frente_al_estandar(doc, k):
    """Requisito en prosa con una duración: se busca el parámetro cuyo nombre está casi entero en el requisito."""
    if doc.codigo.startswith("STD-SEC") or not k.parametros:
        return []
    salida = []
    for r in requisitos_de(doc):
        durs = duraciones_h(r.texto)
        if not durs:
            continue
        q = fichas(r.texto)
        candidatos = [(len(p.claves & q) / len(p.claves), p) for p in k.parametros if p.horas is not None and p.claves]
        cobertura, p = max(candidatos, key=lambda x: x[0], default=(0, None))
        if not p or cobertura < 0.75 or len(p.claves & q) < 2:
            continue
        v = durs[0][0]
        if incumple(p, v):
            salida.append(hallazgo(doc, f"{r.id}{sec(r.seccion)}", "No cumple", clausula_valida(r.clausula),
                                   f"{p.nombre}: el requisito fija «{durs[0][1]}»; {_fuente(p)}.",
                                   "parametros.requisitos", evidencia=r.texto[:240], confianza=0.75, pagina=r.pagina))
    return salida
