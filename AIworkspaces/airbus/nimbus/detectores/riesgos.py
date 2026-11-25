"""
Registros de riesgos (cualquier tabla con columnas de nivel de riesgo): todo se CALCULA con código.

  - Nivel declarado ≠ P × I según la fórmula del estándar vigente             → Inconsistencia
  - Riesgo residual declarado ≠ P res. × I res., o residual > inherente          → Inconsistencia
  - Riesgo Alto sin tratamiento («—», «Ninguno», «asumido»): el estándar dice
    «No aceptables sin tratamiento»                                               → No cumple
"""
import re

from nimbus.conocimiento import norm
from nimbus.detectores.comun import columna, hallazgo, tabla_ref

ORDEN = {"bajo": 0, "medio": 1, "alto": 2}
SIN_TRATAMIENTO = re.compile(r"^(—|-|–|ninguno|ninguna|n/a)$|asumid|sin tratamiento", re.I)


def _num(x):
    try:
        return float(x.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def registros_de_riesgos(doc, k):
    salida = []
    for t in doc.tablas:
        cab = [norm(c) for c in t.cabecera]
        i_niv = next((i for i, c in enumerate(cab) if c == "nivel"), None)
        if i_niv is None:
            continue
        i_id = 0
        i_p = next((i for i, c in enumerate(cab) if c == "p"), None)
        i_i = next((i for i, c in enumerate(cab) if c == "i"), None)
        i_pr = next((i for i, c in enumerate(cab) if c in ("p res.", "p res")), None)
        i_ir = next((i for i, c in enumerate(cab) if c in ("i res.", "i res")), None)
        i_res = next((i for i, c in enumerate(cab) if c.startswith("residual")), None)
        i_trat = columna(t, "tratamiento")
        for f in t.filas:
            rid = f[i_id].split(" ")[0]
            if not re.match(r"^[A-Z]{1,4}(?:-[A-Z0-9]+)*-\d{2,3}$", rid):
                continue
            donde = f"{tabla_ref(t)}, {rid}"
            nivel = norm(f[i_niv])
            p, i = (_num(f[i_p]), _num(f[i_i])) if i_p is not None and i_i is not None else (None, None)
            if p and i and k.umbrales_riesgo:
                calc = k.nivel(p, i)
                if norm(calc) != nivel and nivel in ORDEN:
                    salida.append(hallazgo(doc, donde, "Inconsistencia", "IS.I.OR.205",
                                           f"Nivel declarado «{f[i_niv]}» pero P×I = {p:g}×{i:g} = {p*i:g} → {calc} "
                                           f"según la fórmula del estándar vigente.", "riesgos.nivel",
                                           evidencia=" | ".join(f), confianza=0.9, pagina=t.pagina))
            if i_trat is not None and nivel == "alto" and SIN_TRATAMIENTO.search(f[i_trat].strip()):
                salida.append(hallazgo(doc, donde, "No cumple", "IS.I.OR.210",
                                       f"Riesgo «Alto» sin tratamiento («{f[i_trat]}»); el estándar vigente establece que los "
                                       f"riesgos altos no son aceptables sin tratamiento.", "riesgos.sin_tratamiento",
                                       evidencia=" | ".join(f), confianza=0.9, pagina=t.pagina))
            if i_res is not None:
                res = norm(f[i_res])
                if i_pr is not None and i_ir is not None:
                    pr, ir = _num(f[i_pr]), _num(f[i_ir])
                    if pr and ir and k.umbrales_riesgo and norm(k.nivel(pr, ir)) != res and res in ORDEN:
                        salida.append(hallazgo(doc, donde, "Inconsistencia", "IS.I.OR.210",
                                               f"Residual declarado «{f[i_res]}» pero P res.×I res. = {pr:g}×{ir:g} → "
                                               f"{k.nivel(pr, ir)}.", "riesgos.residual",
                                               evidencia=" | ".join(f), confianza=0.85, pagina=t.pagina))
                        continue
                if res in ORDEN and nivel in ORDEN and ORDEN[res] > ORDEN[nivel]:
                    salida.append(hallazgo(doc, donde, "Inconsistencia", "IS.I.OR.210",
                                           f"Riesgo residual «{f[i_res]}» mayor que el inherente «{f[i_niv]}»: el "
                                           f"tratamiento no puede aumentar el riesgo.", "riesgos.residual",
                                           evidencia=" | ".join(f), confianza=0.85, pagina=t.pagina))
    return salida
