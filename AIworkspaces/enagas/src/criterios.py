"""
Criterios de validación diaria: versión ESTÁNDAR (igual para todas las UM) y versión ADAPTATIVA
(umbral propio de cada UM aprendido de su histórico).

Criterios (definiciones del enunciado de Enagás):
  NC            la UM no tiene resultado correcto ese día (no llegó lectura)
  ERROR         energía o volumen normalizado bajo error (EE / VEn)
  MODULA        el dato diario es modulado
  SERIE         ajuste tipificado como 'Prueba en Serie'
  AJUSTES       ajuste de otro tipo        ┐ son lo que el usuario HIZO ese día → se usan como
  MODIF         lecturas/resultados modif. ┘ ETIQUETA (incidencia confirmada), nunca como entrada
  DIF_PCS       |PCS calculado / PCS cromatógrafo asignado − 1|   (solo UM de Energía)
  DIF_ORION     |Neptuno / ORION − 1|            (energía o volumen según tipo de UM)
  DIF_ORION_ABS |Neptuno − ORION|                (kWh o m3(n))
  DIF_HIS       volumen normalizado vs mismo día de la semana anterior

Regla adaptativa: para cada criterio numérico, lo "normal" de cada UM es hasta su percentil 99,5
de los últimos 365 días (solo días pasados y sin incidencia); se alerta al superarlo en un 25 %.
Para MODULA/SERIE: si en esa UM ocurren a menudo, para ella no son señal de problema.
"""
import numpy as np
import pandas as pd

import config

CRITERIOS_NUM = ["dif_pcs", "dif_orion", "dif_orion_abs", "dif_his"]
NOMBRE = {"nc": "NC", "error": "ERROR", "modula": "MODULA", "serie": "SERIE", "dif_pcs": "DIF_PCS",
          "dif_orion": "DIF_ORION", "dif_orion_abs": "DIF_ORION_ABS", "dif_his": "DIF_HIS"}


def calcular_criterios(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    energia = df["tipo_um"].eq("Energia")
    val_nep = np.where(energia, df["ene_neptuno"], df["vol_neptuno"])
    val_ori = np.where(energia, df["ene_orion"], df["vol_orion"])
    df["valor_neptuno"], df["valor_orion"] = val_nep, val_ori
    df["unidad"] = np.where(energia, "kWh", "m3(n)")

    # --- marcas
    df["nc"] = df["vol_neptuno"].isna() | df["estado_neptuno"].eq("NC")
    df["error"] = df["estado_neptuno"].eq("ERROR")
    df["modula"] = df["modulado"].eq(1)
    df["serie"] = df["ajuste_tipo"].eq("Prueba en Serie")
    # ETIQUETA (proxy de incidencia): el usuario tuvo que modificar o ajustar (salvo 'Prueba en Serie')
    df["etiqueta"] = df["modificado"].eq(1) | ~df["ajuste_tipo"].isin(["", "Prueba en Serie"])

    # --- diferencias numéricas
    df["dif_pcs"] = np.where(energia, (df["pcs_calculado"] / df["pcs_cromatografo"] - 1).abs(), np.nan)
    escala = df.groupby("um_id")["valor_orion"].transform("median").clip(lower=1)
    df["dif_orion_signo"] = (df["valor_neptuno"] - df["valor_orion"]) / df["valor_orion"].clip(lower=0.02 * escala)
    df["dif_orion"] = df["dif_orion_signo"].abs()
    df["dif_orion_abs"] = (df["valor_neptuno"] - df["valor_orion"]).abs()
    vol_escala = df.groupby("um_id")["vol_neptuno"].transform("median").clip(lower=1)
    previo = df.groupby("um_id")["vol_neptuno"].shift(7)
    df["dif_his_signo"] = (df["vol_neptuno"] - previo) / previo.clip(lower=0.02 * vol_escala)
    df["dif_his"] = df["dif_his_signo"].abs()
    return df


def reglas_estandar(df: pd.DataFrame) -> pd.DataFrame:
    u = config.UMBRAL_STD
    abs_umbral = np.where(df["tipo_um"].eq("Energia"), u["dif_orion_abs_energia"], u["dif_orion_abs_volumen"])
    df["umbral_std_dif_pcs"] = u["dif_pcs"]
    df["umbral_std_dif_orion"] = u["dif_orion"]
    df["umbral_std_dif_orion_abs"] = abs_umbral
    df["umbral_std_dif_his"] = u["dif_his"]
    salta = {
        "nc": df["nc"], "error": df["error"], "modula": df["modula"], "serie": df["serie"],
        **{c: df[c] > df[f"umbral_std_{c}"] for c in CRITERIOS_NUM},
    }
    for c, s in salta.items():
        df[f"std_{c}"] = s.fillna(False).astype(bool)
    df["n_criterios_std"] = sum(df[f"std_{c}"].astype(int) for c in salta)
    df["alerta_std"] = df["n_criterios_std"] > 0
    return df


def _cuantil_pasado(df: pd.DataFrame, col: str, grupo: list[str]) -> pd.Series:
    """Percentil del histórico PROPIO de cada UM usando solo días anteriores (sin mirar el futuro)
    y quitando los días que tuvieron incidencia (no son 'lo normal')."""
    limpio = df[col].where(~df["etiqueta"] & ~df["nc"])
    tmp = df[grupo].copy()
    tmp["v"] = limpio
    return (tmp.groupby(grupo)["v"]
              .transform(lambda s: s.shift(1).rolling(config.VENTANA_HISTORICO_DIAS,
                                                      min_periods=config.MIN_DIAS_HISTORICO)
                         .quantile(config.CUANTIL_ADAPTATIVO)))


def reglas_adaptativas(df: pd.DataFrame) -> pd.DataFrame:
    df["fin_de_semana"] = df["fecha"].dt.day_of_week >= 5
    for c in CRITERIOS_NUM:
        grupo = ["um_id", "fin_de_semana"] if c == "dif_his" else ["um_id"]
        propio = _cuantil_pasado(df, c, grupo)
        std = df[f"umbral_std_{c}"]
        # sin histórico suficiente → se usa el estándar; nunca más estricto que 1/5 del estándar
        df[f"umbral_ad_{c}"] = (propio * config.MARGEN_ADAPTATIVO).fillna(std).clip(lower=0.2 * std)
        df[f"exceso_{c}"] = df[c] / df[f"umbral_ad_{c}"]  # >1 = fuera de lo normal para ESTA UM
        df[f"ad_{c}"] = (df[f"exceso_{c}"] > 1).fillna(False)

    for c in ["modula", "serie"]:
        frec = df.groupby("um_id")[c].transform(
            lambda s: s.astype(float).shift(1).rolling(config.VENTANA_HISTORICO_DIAS, min_periods=30).mean())
        df[f"frec_{c}"] = frec.fillna(0)
        df[f"ad_{c}"] = df[c] & (df[f"frec_{c}"] < config.FRECUENCIA_FLAG_HABITUAL)
    df["ad_nc"], df["ad_error"] = df["nc"], df["error"]  # estos siempre son relevantes
    cols = [f"ad_{c}" for c in NOMBRE]
    df["n_criterios_ad"] = df[cols].sum(axis=1)
    df["alerta_ad"] = df["n_criterios_ad"] > 0
    return df
