"""
Score de riesgo por UM y día + clasificación en 3 niveles.

  1. VARIABLES: criterios adaptativos (cuánto se sale cada criterio de lo normal de ESA UM),
     señales de deriva, contador bloqueado, contexto del ramal, contrastación y ajustes previos.
  2. NO SUPERVISADO: Isolation Forest → "qué tan rara es esta combinación de señales".
  3. SUPERVISADO: LightGBM aprende de los días que el usuario tuvo que ajustar/modificar
     (etiqueta proxy, como sugiere el enunciado). Partición temporal: entrena con el pasado,
     calibra los umbrales de nivel con los 2 meses siguientes y se evalúa en lo posterior.
  4. NIVELES (calibrados, no a ojo):
       validación automática candidata  → score por debajo del umbral que conserva el 98 % de incidencias
       revisión prioritaria             → score con precisión ≥ 80 %
       revisión recomendada             → lo intermedio
  5. EXPLICACIÓN: contribución de cada variable al score (valores SHAP nativos de LightGBM).
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import config
from src.criterios import CRITERIOS_NUM

NIVELES = ["Revisión prioritaria", "Revisión recomendada", "Validación automática candidata"]


def construir_variables(df: pd.DataFrame, contrastacion: pd.DataFrame | None) -> pd.DataFrame:
    df = df.copy()
    g = df.groupby("um_id")

    # Deriva: diferencia con ORION de la última semana frente a la habitual de la UM (lenta y creciente)
    media7 = g["dif_orion_signo"].transform(lambda s: s.rolling(7, min_periods=3).mean())
    habitual = g["dif_orion_signo"].transform(lambda s: s.shift(7).rolling(90, min_periods=20).median())
    df["deriva_orion"] = media7 - habitual

    # Contador/conversor bloqueado: el volumen no cambia o es 0 mientras ORION sí registra consumo
    escala = g["valor_orion"].transform("median").clip(lower=1)
    df["igual_que_ayer"] = (df["vol_neptuno"] == g["vol_neptuno"].shift(1)) & (df["vol_neptuno"] > 0)
    df["cero_con_orion"] = (df["vol_neptuno"] <= 0) & (df["valor_orion"] > 0.05 * escala)

    # Efecto ramal: si TODO el ramal sube/baja (frío, festivo), no es un problema de la UM
    df["ramal_dif_his"] = df.groupby(["ramal", "fecha"])["dif_his_signo"].transform("median")
    df["dif_his_vs_ramal"] = df["dif_his_signo"] - df["ramal_dif_his"]

    # Ajustes previos (días con incidencia confirmada en los 90 días anteriores, sin contar hoy)
    df["ajustes_previos_90d"] = g["etiqueta"].transform(lambda s: s.astype(float).shift(1).rolling(90, min_periods=1).sum())

    # Contrastación de contadores (CONTRAS / CONTRAS_OBS): la última anterior o de ese mismo día
    if contrastacion is not None and not contrastacion.empty:
        c = contrastacion.sort_values("fecha").rename(columns={"fecha": "fecha_contraste"})
        c["contraste_con_obs"] = c["observaciones"].fillna("").str.len() > 0
        df = pd.merge_asof(df.sort_values("fecha"), c[["um_id", "fecha_contraste", "error_pct", "contraste_con_obs",
                                                       "observaciones"]].sort_values("fecha_contraste"),
                           left_on="fecha", right_on="fecha_contraste", by="um_id", direction="backward")
        df = df.sort_values(["um_id", "fecha"]).reset_index(drop=True)
        df["dias_desde_contraste"] = (df["fecha"] - df["fecha_contraste"]).dt.days
        df["error_contraste_abs"] = df["error_pct"].abs()
        df["contraste_con_obs"] = df["contraste_con_obs"].fillna(False).astype(bool)
    else:
        df["dias_desde_contraste"] = np.nan
        df["error_contraste_abs"] = np.nan
        df["contraste_con_obs"] = False
        df["observaciones"] = ""
    df["tipo_consumo_cod"] = df["tipo_consumo"].astype("category").cat.codes
    df["es_energia"] = df["tipo_um"].eq("Energia").astype(int)
    return df


VARIABLES = (
    [f"exceso_{c}" for c in CRITERIOS_NUM]
    + ["dif_orion_signo", "dif_his_signo", "deriva_orion", "dif_his_vs_ramal", "ramal_dif_his",
       "nc", "error", "ad_modula", "serie", "frec_modula", "igual_que_ayer", "cero_con_orion",
       "ajustes_previos_90d", "dias_desde_contraste", "error_contraste_abs", "contraste_con_obs",
       "tipo_consumo_cod", "es_energia", "rareza_iforest"]
)


def _matriz(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    X = df[columnas].copy()
    for c in X:
        if X[c].dtype == bool:
            X[c] = X[c].astype(int)
    return X.astype(float).replace([np.inf, -np.inf], np.nan)


def entrenar_y_puntuar(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    fin_ent = pd.Timestamp(config.FECHA_FIN_ENTRENAMIENTO)
    fin_cal = pd.Timestamp(config.FECHA_FIN_CALIBRACION)
    df["particion"] = np.select([df["fecha"] <= fin_ent, df["fecha"] <= fin_cal], ["entrenamiento", "calibracion"], "prueba")
    ent = df["particion"].eq("entrenamiento")

    # --- Isolation Forest (no supervisado) sobre las señales numéricas
    base_if = [f"exceso_{c}" for c in CRITERIOS_NUM] + ["deriva_orion", "dif_his_vs_ramal"]
    Xif = _matriz(df, base_if).fillna(0).clip(-50, 50)
    iforest = IsolationForest(n_estimators=200, contamination="auto", random_state=0)
    iforest.fit(Xif[ent & ~df["etiqueta"]])
    df["rareza_iforest"] = -iforest.score_samples(Xif)

    # --- LightGBM (supervisado con etiqueta proxy)
    X = _matriz(df, VARIABLES)
    y = df["etiqueta"].astype(int)
    modelo = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=40,
                                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
    modelo.fit(X[ent], y[ent])
    df["score"] = modelo.predict_proba(X)[:, 1]

    # --- Umbrales de nivel calibrados en el periodo de calibración (datos no vistos al entrenar)
    cal = df["particion"].eq("calibracion")
    s_pos = df.loc[cal & df["etiqueta"], "score"].values
    t_auto = float(np.quantile(s_pos, 1 - config.RECALL_MINIMO_AUTO)) if len(s_pos) else 0.05
    # prioritaria: el umbral más bajo con el que las de arriba siguen teniendo precisión ≥ 80 %
    orden_cal = df.loc[cal, ["score", "etiqueta"]].sort_values("score", ascending=False)
    k = np.arange(1, len(orden_cal) + 1)
    precision_acum = orden_cal["etiqueta"].cumsum().values / k
    validos = np.where((k >= 10) & (precision_acum >= config.PRECISION_PRIORITARIA))[0]
    if len(validos):
        t_prio = float(orden_cal["score"].values[validos[-1]])
    else:
        t_prio = float(np.quantile(df.loc[cal, "score"], 0.99))
    t_prio = max(t_prio, t_auto + 1e-6)
    df["nivel"] = np.select([df["score"] >= t_prio, df["score"] >= t_auto], NIVELES[:2], NIVELES[2])

    # --- Contribuciones (SHAP nativo de LightGBM): por qué cada UM-día tiene ese score
    contrib = modelo.booster_.predict(X, pred_contrib=True)[:, :-1]
    orden = np.argsort(-contrib, axis=1)[:, :3]
    for k in range(3):
        df[f"var_{k + 1}"] = np.array(VARIABLES)[orden[:, k]]
        df[f"aporte_{k + 1}"] = contrib[np.arange(len(df)), orden[:, k]]

    importancia = pd.Series(np.abs(contrib[ent.values]).mean(axis=0), index=VARIABLES).sort_values(ascending=False)
    info = {"umbral_auto": t_auto, "umbral_prioritaria": t_prio,
            "importancia": importancia.round(4).to_dict()}
    return df, info
