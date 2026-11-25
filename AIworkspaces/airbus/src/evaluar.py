"""
Métricas del jurado contra el gold set.

  - Detección de incumplimientos (30 %): precisión, recall y F1.
      · estricto: solo cuenta lo marcado "No cumple"
      · señalados: "No cumple" + "Revisar" (lo que llega al revisor humano)
  - Trazabilidad (20 %, referencia ≥ 90 %): % de hallazgos cuya cláusula citada es la del gold.
  - Cobertura: reglas IR de Part-IS tocadas por algún requisito.
  - Consistencia: precisión/recall de las contradicciones detectadas.
"""
import pandas as pd

import config


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "tp": tp, "fp": fp, "fn": fn}


def gold_disponible() -> bool:
    return (config.DIR_DATOS / config.GOLD).exists()


def evaluar(hallazgos: pd.DataFrame, contradicciones: pd.DataFrame) -> dict:
    gold = pd.read_csv(config.DIR_DATOS / config.GOLD).fillna("")
    df = hallazgos.merge(gold, on="req_id", how="inner")
    positivo_gold = df.veredicto_gold == "No cumple"

    def det(pred):
        return _prf(int((pred & positivo_gold).sum()), int((pred & ~positivo_gold).sum()), int((~pred & positivo_gold).sum()))

    estricto = det(df.veredicto == "No cumple")
    senalados = det(df.veredicto.isin(["No cumple", "Revisar"]))

    aplicables = df[df.clausula_gold != ""]
    traz_ok = (aplicables.clausula == aplicables.clausula_gold)
    trazabilidad = round(traz_ok.mean(), 3) if len(aplicables) else None
    exactitud = round((df.veredicto.replace({"Revisar": "No cumple"}) == df.veredicto_gold).mean(), 3)

    m = {"n_requisitos": len(df), "deteccion_estricta": estricto, "deteccion_senalados": senalados,
         "trazabilidad_pct": trazabilidad, "exactitud_veredicto": exactitud,
         "errores_trazabilidad": aplicables.loc[~traz_ok, ["req_id", "clausula", "clausula_gold"]].to_dict("records")}

    gc_path = config.DIR_DATOS / "gold_contradicciones.csv"
    if gc_path.exists():
        gc = pd.read_csv(gc_path)
        pares_gold = {frozenset(x) for x in gc[["req_a", "req_b"]].values.tolist()}
        pares_pred = {frozenset(x) for x in contradicciones[["req_a", "req_b"]].values.tolist()} if len(contradicciones) else set()
        tp = len(pares_gold & pares_pred)
        m["contradicciones"] = _prf(tp, len(pares_pred - pares_gold), len(pares_gold - pares_pred))
    return m
