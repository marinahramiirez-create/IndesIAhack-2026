"""
Matrices e informes de verificación.

  sin_verificacion            un control con método de verificación «N/A»/«—» (no se verifica), o declarado
                              «Conforme» sin evidencia.
  cobertura_de_verificacion   un informe de verificación que no incluye todos los requisitos de la especificación
                              que verifica, o cuyo resumen no cuadra con el detalle.
"""
import re

from nimbus.conocimiento import norm
from nimbus.detectores.comun import columna, hallazgo, tabla_ref

VACIO = {"—", "-", "–", "n/a", "na", ""}


def _clausula_de(rid, k, doc):
    # Verificar un control es comprobar que la medida es eficaz: IS.I.OR.210(a) («comprobará que siguen siendo eficaces»)
    return "IS.I.OR.210"


def sin_verificacion(doc, k):
    salida = []
    for t in doc.tablas:
        ir = columna(t, "requisito")
        im = columna(t, "metodo")
        ires, iev = columna(t, "resultado"), columna(t, "evidencia")
        if ir is None or (im is None and ires is None):
            continue
        for f in t.filas:
            rid = f[ir].split(" ")[0]
            if not re.match(r"^[A-Z0-9]{2,4}-SEC-\d{3}$|^SEC-REQ-\d{3}$", rid):
                continue
            if im is not None and norm(f[im]).strip(".") in VACIO:
                salida.append(hallazgo(doc, f"{tabla_ref(t)}, {rid}", "No cumple", _clausula_de(rid, k, doc),
                                       f"Control {rid} con método de verificación «{f[im]}»: queda sin verificar.",
                                       "verificacion.sin_metodo", evidencia=" | ".join(f), confianza=0.8, pagina=t.pagina))
            elif ires is not None and iev is not None and "conforme" == norm(f[ires]) and norm(f[iev]) in VACIO:
                salida.append(hallazgo(doc, f"{tabla_ref(t)}, {rid}", "No verificable", _clausula_de(rid, k, doc),
                                       f"{rid} declarado «Conforme» sin evidencia («{f[iev]}»).",
                                       "verificacion.sin_evidencia", evidencia=" | ".join(f), confianza=0.8, pagina=t.pagina))
    return salida


def cobertura_de_verificacion(doc, k):
    """Informe IVS-SEC-X: ¿verifica todos los requisitos de la especificación SRS-SEC-X? ¿cuadra su resumen?"""
    m = re.match(r"^IVS-SEC-([A-Z0-9]+)$", doc.codigo)
    if not m:
        return []
    salida = []
    prefijo = f"{m.group(1)}-SEC"
    esperados = k.ids_por_prefijo.get(prefijo, set())
    # tabla(s) de resultados: Requisito | … | Resultado con ≥3 columnas (la de resumen tiene 2); puede ocupar varias páginas
    tablas_res = [t for t in doc.tablas if columna(t, "requisito") is not None and columna(t, "resultado") is not None
                  and len(t.cabecera) >= 3]
    if not tablas_res:
        return []
    resultados = tablas_res[0]
    ir = columna(resultados, "requisito")
    filas_res = [f for t in tablas_res for f in t.filas]
    vistos = {f[columna(t, "requisito")].split(" ")[0] for t in tablas_res for f in t.filas}
    faltan = sorted(i for i in esperados if i not in vistos and re.match(rf"^{prefijo}-\d{{3}}$", i))
    if faltan and len(faltan) <= 0.2 * max(len(esperados), 1):   # un hueco enorme sería un fallo de lectura, no un defecto
        salida.append(hallazgo(doc, f"{tabla_ref(resultados)}, documento completo", "Cobertura faltante", "IS.I.OR.210",
                               f"El informe no verifica {len(faltan)} requisito(s) de la especificación: "
                               f"{', '.join(faltan[:8])}{'…' if len(faltan) > 8 else ''}.",
                               "verificacion.cobertura", confianza=0.8, pagina=resultados.pagina))
    # el resumen (Total verificados = N) frente al número real de filas
    for t in doc.tablas:
        if t in tablas_res or len(t.cabecera) != 2:
            continue
        total = next((f for f in t.filas if "total" in norm(f[0])), None)
        if total and re.match(r"^\d+$", total[1].strip()):
            n_real = len([f for f in filas_res if re.match(rf"^{prefijo}-\d{{3}}", f[ir])])
            if int(total[1]) != n_real:
                salida.append(hallazgo(doc, f"{tabla_ref(t)} ↔ tabla de resultados", "Inconsistencia", "IS.I.OR.245",
                                       f"El resumen declara {total[1]} requisitos verificados, pero la tabla de resultados "
                                       f"tiene {n_real}.", "verificacion.resumen", evidencia=" | ".join(total),
                                       confianza=0.85, pagina=t.pagina))
    return salida
