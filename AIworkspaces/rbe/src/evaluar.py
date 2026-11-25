"""
Métricas de calidad: F1 contra las anomalías inyectadas (datos sintéticos).

Con datos reales no hay etiquetas: entonces se usa precision@K revisada por el equipo
(las decisiones aprobar/descartar de la interfaz) o se inyectan anomalías artificiales
sobre los datos reales (backtesting) con inyectar_en_reales().
"""
import pandas as pd

import config


def _emparejar(det: pd.DataFrame, ver: pd.DataFrame, tolerancia_dias: int) -> tuple[int, set]:
    """Empareja cada etiqueta con como mucho una detección de la misma serie dentro de la tolerancia."""
    usadas: set = set()
    tp = 0
    for _, e in ver.iterrows():
        cand = det[(det.restaurante_id == e.restaurante_id) & (det.canal == e.canal)
                   & ((det.fecha - e.fecha).abs().dt.days <= tolerancia_dias)
                   & (~det.index.isin(usadas))]
        if not cand.empty:
            mejor = (cand.fecha - e.fecha).abs().idxmin()
            usadas.add(mejor)
            tp += 1
    return tp, usadas


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 3), round(r, 3), round(f1, 3)


def evaluar(alertas: pd.DataFrame, etiquetas: pd.DataFrame | None, k: int = 20) -> pd.DataFrame:
    if etiquetas is None or etiquetas.empty:
        return pd.DataFrame()
    filas = []
    tp_tot = fp_tot = fn_tot = 0
    for tipo, tol in [("puntual", config.TOLERANCIA_DIAS_PUNTUAL), ("tendencia", config.TOLERANCIA_DIAS_TENDENCIA)]:
        det = alertas[alertas.tipo == tipo]
        ver = etiquetas[etiquetas.tipo == tipo]
        tp, usadas = _emparejar(det, ver, tol)
        resto = det[~det.index.isin(usadas)]
        # Una alerta puntual justo en el inicio de un cambio de tendencia real no es un falso positivo:
        # está señalando el mismo problema. Se cuenta como "relacionada", no como error.
        relacionadas = 0
        if tipo == "puntual":
            tend = etiquetas[etiquetas.tipo == "tendencia"]
            for _, a in resto.iterrows():
                cerca = tend[(tend.restaurante_id == a.restaurante_id) & (tend.canal == a.canal)
                             & ((tend.fecha - a.fecha).abs().dt.days <= 7)]
                relacionadas += int(not cerca.empty)
        fp = len(resto) - relacionadas
        fn = len(ver) - tp
        p, r, f1 = _prf(tp, fp, fn)
        filas.append({"tipo": tipo, "etiquetas": len(ver), "detectadas": len(det), "acertadas": tp,
                      "falsos_positivos": fp, "no_detectadas": fn, "precision": p, "recall": r, "f1": f1})
        tp_tot, fp_tot, fn_tot = tp_tot + tp, fp_tot + fp, fn_tot + fn
    p, r, f1 = _prf(tp_tot, fp_tot, fn_tot)
    filas.append({"tipo": "global", "etiquetas": len(etiquetas), "detectadas": len(alertas), "acertadas": tp_tot,
                  "falsos_positivos": fp_tot, "no_detectadas": fn_tot, "precision": p, "recall": r, "f1": f1})

    # precision@K: de las K primeras de la bandeja, ¿cuántas son reales?
    top = alertas.head(k)
    aciertos = 0
    for _, a in top.iterrows():
        tol = config.TOLERANCIA_DIAS_TENDENCIA if a.tipo == "tendencia" else 7
        m = etiquetas[(etiquetas.restaurante_id == a.restaurante_id) & (etiquetas.canal == a.canal)
                      & ((etiquetas.fecha - a.fecha).abs().dt.days <= tol)]
        aciertos += int(not m.empty)
    filas.append({"tipo": f"precision@{k}", "precision": round(aciertos / max(len(top), 1), 3)})
    return pd.DataFrame(filas)
