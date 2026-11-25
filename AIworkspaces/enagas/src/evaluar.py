"""
Métricas (sobre el periodo de PRUEBA, que el modelo no ha visto):

  - Para cada enfoque (regla estándar, regla adaptativa, modelo): revisiones/día, precisión, recall, F1.
    Se evalúa contra la etiqueta proxy (ajustes/modificaciones del usuario) y, si hay datos
    sintéticos, también contra las incidencias reales inyectadas.
  - % de UM-día candidatas a validación automática y cuántas incidencias se escaparían ahí.
  - Reducción de revisiones manuales frente a la regla estándar.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


def _prf(alerta: pd.Series, verdad: pd.Series) -> dict:
    tp = int((alerta & verdad).sum())
    p = tp / alerta.sum() if alerta.sum() else 0.0
    r = tp / verdad.sum() if verdad.sum() else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}


def evaluar(df: pd.DataFrame) -> dict:
    t = df[df["particion"] == "prueba"]
    dias = t["fecha"].nunique()
    verdades = {"etiqueta_proxy": t["etiqueta"]}
    if "incidencia_real" in t:
        verdades["incidencia_real"] = t["incidencia_real"]

    enfoques = {
        "Regla estándar (actual)": t["alerta_std"],
        "Regla adaptativa por UM": t["alerta_ad"],
        "Modelo IA: prioritaria + recomendada": t["nivel"] != "Validación automática candidata",
        "Modelo IA: solo prioritaria": t["nivel"] == "Revisión prioritaria",
    }
    filas = []
    for nombre, alerta in enfoques.items():
        fila = {"enfoque": nombre, "revisiones_dia": round(alerta.sum() / dias, 1),
                "pct_um_dia_revisadas": round(100 * alerta.mean(), 1)}
        for vn, v in verdades.items():
            fila.update({f"{k}_{vn}": val for k, val in _prf(alerta, v).items()})
        filas.append(fila)
    comparativa = pd.DataFrame(filas)

    auto = t["nivel"] == "Validación automática candidata"
    v = verdades.get("incidencia_real", t["etiqueta"])
    resumen = {
        "dias_prueba": int(dias),
        "um": int(t["um_id"].nunique()),
        "pct_validacion_automatica": round(100 * auto.mean(), 1),
        "incidencias_escapadas_en_auto_pct": round(100 * (auto & v).sum() / max(v.sum(), 1), 1),
        "reduccion_revisiones_vs_estandar_pct": round(100 * (1 - (~auto).sum() / max(t["alerta_std"].sum(), 1)), 1),
        "auc_pr_modelo": round(float(average_precision_score(t["etiqueta"], t["score"])), 3),
        "incidencias_reales_disponibles": "incidencia_real" in t,
    }
    reparto = t["nivel"].value_counts().to_dict()

    # recall por tipo de incidencia (solo sintético): ¿qué tipos se nos escapan?
    por_tipo = {}
    if "tipo_incidencia" in t:
        r = t[t["incidencia_real"]]
        por_tipo = (r.assign(detectada=r["nivel"] != "Validación automática candidata")
                     .groupby("tipo_incidencia")["detectada"].mean().round(3).to_dict())
    return {"comparativa": comparativa.to_dict(orient="records"), "resumen": resumen,
            "reparto_niveles": reparto, "recall_por_tipo": por_tipo}
