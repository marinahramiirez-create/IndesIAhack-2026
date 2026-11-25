"""
Motor de detección de anomalías (Motor A adaptado a RBE).

Idea en 4 pasos, por cada serie restaurante × canal:
  1. PATRÓN ESPERADO: mediana del mismo día de la semana en las 6 semanas anteriores (en log).
  2. QUITAR RUIDO CONOCIDO: a la desviación se le resta lo que les pasa ese mismo día a sus PARES
     (misma marca → campañas; misma tipología → festivos). Si además la mayoría de la ZONA se
     desvía igual, es un evento externo (temporal, concierto...) y se descarta.
  3. PUNTUALES: z-score robusto (mediana y MAD) de la desviación limpia. |z| >= umbral → alerta.
  4. TENDENCIAS: serie semanal relativa a los pares + detección de cambios de nivel (ruptures).

Todo lo calcula el código. El LLM nunca toca estos números.
"""
import numpy as np
import pandas as pd
import ruptures as rpt

import config


def sigma_robusta(x) -> float:
    x = np.asarray(x, dtype=float)
    # se ignoran los ceros exactos: aparecen cuando el restaurante ES la mediana de su grupo
    # y, si se contasen, harían parecer el ruido más pequeño de lo que es
    x = x[~np.isnan(x) & (np.abs(x) > 1e-9)]
    if len(x) == 0:
        return 1.0
    mad = np.median(np.abs(x - np.median(x)))
    if mad > 0:
        return 1.4826 * mad
    return float(np.std(x)) or 1.0


def _restar_mediana_pares(df: pd.DataFrame, col: str, grupo: list[str], clave_tiempo: str, minimo: int = 4):
    """Resta a cada valor la mediana de su grupo de pares en el mismo instante.
    Si el grupo tiene menos de `minimo` miembros, no se ajusta. Devuelve (valor_ajustado, efecto)."""
    g = df.groupby(grupo + [clave_tiempo])[col]
    mediana = g.transform("median")
    n = g.transform("count")
    efecto = np.where(n >= minimo, mediana, 0.0)
    return df[col] - efecto, efecto


# Solo dos efectos por día: marca (campañas) y tipología (festivos afectan distinto a un
# centro comercial que a un local de calle). Más grupos = se "come" el ruido y exagera los extremos.
# La zona se usa después como filtro explicable de eventos externos (ver marcar_eventos_zona).
GRUPOS_PARES = [["marca", "canal"], ["tipologia", "canal"]]


def _pulir_por_pares(df: pd.DataFrame, col: str, clave_tiempo: str, iteraciones: int = 4) -> pd.Series:
    """'Median polish': quita por turnos el efecto de marca y de tipología, varias veces,
    porque los dos efectos se mezclan entre sí."""
    tmp = df[["marca", "canal", "tipologia", clave_tiempo]].copy()
    tmp["r"] = df[col].values
    for _ in range(iteraciones):
        for grupo in GRUPOS_PARES:
            tmp["r"], _ = _restar_mediana_pares(tmp, "r", grupo, clave_tiempo)
    return tmp["r"]


# ---------------------------------------------------------------------------
# 1-3. Esperado diario + anomalías puntuales
# ---------------------------------------------------------------------------
def calcular_esperado(ventas: pd.DataFrame, restaurantes: pd.DataFrame) -> pd.DataFrame:
    cols_rest = [c for c in ["restaurante_id", "marca", "zona", "tipologia"] if c in restaurantes]
    df = ventas.merge(restaurantes[cols_rest], on="restaurante_id", how="left")
    df = df.sort_values(["restaurante_id", "canal", "fecha"]).reset_index(drop=True)
    df["log_v"] = np.log1p(df["ventas"].clip(lower=0))
    df["dow"] = df["fecha"].dt.day_of_week

    # Paso 1: patrón esperado = mediana del mismo día de la semana en las N semanas ANTERIORES.
    # No usa el propio día (si lo usara, "aprendería" la anomalía) ni el futuro (como en producción).
    por_dia = df.groupby(["restaurante_id", "canal", "dow"])["log_v"]
    df["base_log"] = por_dia.transform(
        lambda s: s.shift(1).rolling(config.SEMANAS_BASE, min_periods=3).median())
    df["resid_bruto"] = df["log_v"] - df["base_log"]

    # Paso 2: descontar lo que les pasa a los pares el mismo día (campañas, festivos...)
    df["residuo"] = _pulir_por_pares(df, "resid_bruto", "fecha")

    # Paso 3: z robusto por serie (antes y después de quitar el ruido, para medir cuánto filtramos)
    grp = df.groupby(["restaurante_id", "canal"])
    df["z_bruto"] = df["resid_bruto"] / grp["resid_bruto"].transform(sigma_robusta)
    df["z"] = df["residuo"] / grp["residuo"].transform(sigma_robusta)
    df["esperado"] = np.expm1(df["log_v"] - df["residuo"]).round(2)
    df["evento_zona"] = marcar_eventos_zona(df)

    # Referencia "mismo día de la semana, últimas 4 semanas" para separar tickets vs ticket medio
    for col in ["tickets", "ticket_medio"]:
        df[f"ref_{col}"] = (df.groupby(["restaurante_id", "canal", "dow"])[col]
                              .transform(lambda s: s.shift(1).rolling(4, min_periods=2).median()))
    return df


def marcar_eventos_zona(df: pd.DataFrame, z_vecino: float = 2.0, fraccion: float = 0.5) -> pd.Series:
    """True si al menos la mitad de los OTROS restaurantes de la zona (mismo canal, mismo día)
    se desvían en la misma dirección. Eso es un evento externo (temporal, concierto...), no
    un problema del restaurante."""
    clave = ["zona", "canal", "fecha"]
    sube = (df["z"] >= z_vecino).astype(int)
    baja = (df["z"] <= -z_vecino).astype(int)
    n_otros = df.groupby(clave)["z"].transform("count") - 1
    otros_suben = df.assign(s=sube).groupby(clave)["s"].transform("sum") - sube
    otros_bajan = df.assign(b=baja).groupby(clave)["b"].transform("sum") - baja
    mismos = np.where(df["z"] > 0, otros_suben, otros_bajan)
    return (n_otros >= 2) & (mismos >= fraccion * n_otros)


def anomalias_puntuales(df: pd.DataFrame) -> pd.DataFrame:
    th = config.UMBRAL_Z_PUNTUAL
    relevante = np.abs(np.expm1(df["residuo"])) >= config.UMBRAL_DESVIACION_MIN
    a = df[(df["z"].abs() >= th) & relevante & (~df["evento_zona"])].copy()
    a["tipo"] = "puntual"
    a["fecha_fin"] = a["fecha"]
    a["real"] = a["ventas"]
    a["impacto_eur"] = (a["ventas"] - a["esperado"]).round(0)
    a["desviacion_pct"] = ((a["ventas"] / a["esperado"] - 1) * 100).round(1)
    a["var_tickets_pct"] = ((a["tickets"] / a["ref_tickets"] - 1) * 100).round(1)
    a["var_ticket_medio_pct"] = ((a["ticket_medio"] / a["ref_ticket_medio"] - 1) * 100).round(1)
    a["efecto_pares_pct"] = (np.expm1(a["resid_bruto"] - a["residuo"]) * 100).round(1)
    a["score"] = a["z"].abs().round(2)
    a["semanas"] = 0
    a["prioridad"] = a["impacto_eur"].abs() * np.minimum(a["score"] / th, 3)
    return a


# ---------------------------------------------------------------------------
# 4. Cambios de tendencia
# ---------------------------------------------------------------------------
def cambios_tendencia(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["semana"] = d["fecha"].dt.to_period("W-SUN").dt.start_time
    sem = (d.groupby(["restaurante_id", "canal", "marca", "zona", "tipologia", "semana"])
             .agg(ventas=("ventas", "sum"), dias=("ventas", "size")).reset_index())
    sem = sem[sem["dias"] == 7].copy()  # solo semanas completas
    sem["x"] = np.log(sem["ventas"].clip(lower=1))
    sem["x"] = sem["x"] - sem.groupby(["restaurante_id", "canal"])["x"].transform("mean")
    sem["x"] = _pulir_por_pares(sem, "x", "semana").values

    filas = []
    for (rid, canal), s in sem.groupby(["restaurante_id", "canal"]):
        s = s.sort_values("semana").reset_index(drop=True)
        x = s["x"].values
        n = len(x)
        if n < 12:
            continue
        sigma = sigma_robusta(np.diff(x)) / np.sqrt(2)
        pen = 3 * sigma ** 2 * np.log(n)
        cortes = rpt.Pelt(model="l2", min_size=3).fit(x).predict(pen=pen)
        limites = [0] + cortes  # el último corte siempre es n
        for i in range(1, len(limites) - 1):
            ini, b, fin = limites[i - 1], limites[i], limites[i + 1]
            antes, despues = x[ini:b], x[b:fin]
            delta = despues.mean() - antes.mean()
            cambio = np.expm1(delta)
            if abs(cambio) < config.UMBRAL_CAMBIO_TENDENCIA:
                continue
            ventas_desp = s["ventas"].values[b:fin]
            impacto = float(np.sum(ventas_desp * (1 - np.exp(-delta))))
            sev = abs(delta) / sigma
            filas.append({
                "restaurante_id": rid, "canal": canal, "marca": s["marca"][0], "zona": s["zona"][0],
                "tipologia": s["tipologia"][0], "tipo": "tendencia",
                "fecha": s["semana"][b], "fecha_fin": s["semana"][fin - 1] + pd.Timedelta(days=6),
                "real": round(float(ventas_desp.mean()), 2),
                "esperado": round(float(ventas_desp.mean() / np.exp(delta)), 2),
                "desviacion_pct": round(cambio * 100, 1),
                "impacto_eur": round(impacto, 0),
                "score": round(sev, 2), "semanas": int(fin - b),
                "prioridad": abs(impacto) * min(sev / 3, 3),
            })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
def contexto_dia(fecha, marca, calendario: pd.DataFrame | None, campanas: pd.DataFrame | None) -> str:
    trozos = []
    if calendario is not None:
        fila = calendario[calendario["fecha"] == fecha]
        if not fila.empty:
            f = fila.iloc[0]
            if bool(f.get("festivo", False)):
                trozos.append(f"festivo ({f.get('nombre_festivo', '')})".replace(" ()", ""))
            if isinstance(f.get("evento"), str) and f.get("evento"):
                trozos.append(f"evento: {f['evento']}")
            if bool(f.get("no_lectivo", False)):
                trozos.append("periodo no lectivo")
    if campanas is not None:
        c = campanas[(campanas["marca"] == marca) & (pd.to_datetime(campanas["inicio"]) <= fecha)
                     & (pd.to_datetime(campanas["fin"]) >= fecha)]
        trozos += [f"campaña '{n}'" for n in c["nombre"]]
    return ", ".join(trozos)


def absorber_en_tendencias(punt: pd.DataFrame, tend: pd.DataFrame, dias_antes: int = 7,
                           dias_despues: int = 7 * config.SEMANAS_BASE) -> tuple[pd.DataFrame, int]:
    """Tras un cambio de nivel, el patrón esperado tarda unas semanas en adaptarse y saltarían
    muchas alertas puntuales seguidas. Son el mismo problema: se agrupan en la alerta de tendencia."""
    if tend.empty or punt.empty:
        return punt, 0
    m = punt.reset_index().merge(
        tend[["restaurante_id", "canal", "fecha"]].rename(columns={"fecha": "f_cambio"}),
        on=["restaurante_id", "canal"])
    dias = (m["fecha"] - m["f_cambio"]).dt.days
    quitar = set(m.loc[(dias >= -dias_antes) & (dias <= dias_despues), "index"])
    return punt.drop(index=list(quitar)), len(quitar)


def semaforo(prioridad: pd.Series) -> pd.Series:
    """Top 20 % → alta, siguiente 30 % → media, resto → baja."""
    rango = prioridad.rank(pct=True, ascending=False)
    return np.select([rango <= 0.20, rango <= 0.50], ["alta", "media"], "baja")


def detectar(datos: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Devuelve (alertas, serie_diaria_con_esperado, estadisticas_de_ruido)."""
    serie = calcular_esperado(datos["ventas"], datos["restaurantes"])
    punt = anomalias_puntuales(serie)
    tend = cambios_tendencia(serie)
    punt, absorbidas = absorber_en_tendencias(punt, tend)
    alertas = pd.concat([punt, tend], ignore_index=True)

    alertas["contexto"] = [contexto_dia(f, m, datos["calendario"], datos["campanas"])
                           for f, m in zip(alertas["fecha"], alertas["marca"])]
    alertas["metrica"] = "ventas"
    alertas["alerta_id"] = (alertas["tipo"].str[0].str.upper() + "-" + alertas["restaurante_id"] + "-"
                            + alertas["canal"] + "-" + alertas["fecha"].dt.strftime("%Y%m%d"))
    alertas["semaforo"] = semaforo(alertas["prioridad"])
    alertas = alertas.sort_values("prioridad", ascending=False).reset_index(drop=True)

    th = config.UMBRAL_Z_PUNTUAL
    n_bruto = int((serie["z_bruto"].abs() >= th).sum())
    n_limpio = len(punt)
    ruido = {
        "alertas_sin_filtrar": n_bruto,
        "alertas_tras_filtrar": n_limpio,
        "eventos_zona_descartados": int(((serie["z"].abs() >= th) & serie["evento_zona"]).sum()),
        "agrupadas_en_tendencias": absorbidas,
        "ruido_reducido_pct": round(100 * (1 - n_limpio / n_bruto), 1) if n_bruto else 0.0,
    }
    columnas = ["alerta_id", "tipo", "semaforo", "restaurante_id", "marca", "zona", "tipologia", "canal",
                "fecha", "fecha_fin", "metrica", "real", "esperado", "desviacion_pct", "impacto_eur",
                "score", "semanas", "prioridad", "var_tickets_pct", "var_ticket_medio_pct",
                "efecto_pares_pct", "contexto"]
    alertas = alertas.reindex(columns=columnas)
    serie_out = serie[["restaurante_id", "canal", "marca", "zona", "fecha", "ventas", "tickets",
                       "ticket_medio", "esperado", "z"]]
    return alertas, serie_out, ruido
