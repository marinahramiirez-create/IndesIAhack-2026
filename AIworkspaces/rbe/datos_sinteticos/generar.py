"""
Generador de datos sintéticos que imitan el formato del reto RBE.

Crea en datos_sinteticos/salida/:
  restaurantes.csv  maestro (marca, país, provincia, zona, tipología)
  calendario.csv    festivos, no lectivos, eventos
  campanas.csv      campañas de marketing por marca
  ventas.csv        ventas diarias por restaurante y canal (ventas, tickets, ticket medio)
  etiquetas.csv     anomalías INYECTADAS (la "verdad" para calcular F1). Con datos reales no existe.

Además mete "ruido" que NO es anomalía (festivos, campañas, eventos de zona como un temporal),
para demostrar que el sistema sabe distinguirlo.

Ejecutar:  python datos_sinteticos/generar.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 42
FECHA_INI, FECHA_FIN = "2024-01-01", "2025-06-30"
N_RESTAURANTES = 30
N_PUNTUALES = 40
N_TENDENCIAS = 8
SALIDA = Path(__file__).resolve().parent / "salida"

rng = np.random.default_rng(SEMILLA)

ZONAS = {  # zona -> provincia
    "Madrid-Centro": "Madrid", "Madrid-Norte": "Madrid", "Barcelona": "Barcelona",
    "Valencia": "Valencia", "Sevilla": "Sevilla", "Bilbao": "Bizkaia",
}
MARCAS = {"Burger King": 0.6, "Popeyes": 0.2, "Tim Hortons": 0.2}
TICKET_MEDIO = {"Burger King": 9.5, "Popeyes": 11.0, "Tim Hortons": 6.5}
TIPOLOGIAS = ["calle", "centro_comercial", "autopista"]
CANALES = {"sala": 300, "llevar": 120, "delivery": 90}  # tickets/día base

# Peso de cada día de la semana (lunes=0) según tipología
PATRON_SEMANAL = {
    "calle":            [0.85, 0.85, 0.90, 0.95, 1.15, 1.25, 1.05],
    "centro_comercial": [0.75, 0.75, 0.80, 0.85, 1.10, 1.45, 1.30],
    "autopista":        [0.90, 0.85, 0.85, 0.95, 1.25, 1.05, 1.20],
}

FESTIVOS = {
    "2024-01-01": "Año Nuevo", "2024-01-06": "Reyes", "2024-03-29": "Viernes Santo",
    "2024-05-01": "Día del Trabajo", "2024-08-15": "Asunción", "2024-10-12": "Fiesta Nacional",
    "2024-11-01": "Todos los Santos", "2024-12-06": "Constitución", "2024-12-25": "Navidad",
    "2025-01-01": "Año Nuevo", "2025-01-06": "Reyes", "2025-04-18": "Viernes Santo",
    "2025-05-01": "Día del Trabajo",
}
EVENTOS = {"2024-06-01": "Final Champions", "2024-07-14": "Final Eurocopa", "2025-05-31": "Final Champions"}
CAMPANAS = [
    ("Burger King", "2024-03-04", "2024-03-17", "Whopper 2x1"),
    ("Burger King", "2024-10-07", "2024-10-20", "King Ahorro"),
    ("Burger King", "2025-03-10", "2025-03-23", "Whopper 2x1"),
    ("Popeyes", "2024-05-13", "2024-05-26", "Pollo Cajún"),
    ("Popeyes", "2025-02-03", "2025-02-16", "Menú Louisiana"),
    ("Tim Hortons", "2024-11-11", "2024-11-24", "Pumpkin Spice"),
    ("Tim Hortons", "2025-01-20", "2025-02-02", "Café+Donut"),
]
# Eventos locales que afectan a TODA una zona (no son anomalías del restaurante)
EVENTOS_ZONA = [
    ("Valencia", "2024-10-29", 0.45, "Temporal / DANA"),
    ("Valencia", "2024-10-30", 0.55, "Temporal / DANA"),
    ("Madrid-Centro", "2024-09-14", 1.35, "Concierto"),
    ("Sevilla", "2025-04-09", 1.30, "Feria de Abril"),
    ("Bilbao", "2024-08-20", 1.25, "Aste Nagusia"),
]


def no_lectivo(f: pd.Timestamp) -> bool:
    return (f.month in (7, 8)) or (f.month == 12 and f.day >= 23) or (f.month == 1 and f.day <= 7)


def generar_restaurantes() -> pd.DataFrame:
    filas = []
    zonas = list(ZONAS)
    for i in range(N_RESTAURANTES):
        zona = zonas[i % len(zonas)]
        filas.append({
            "restaurante_id": f"R{i + 1:03d}",
            "marca": rng.choice(list(MARCAS), p=list(MARCAS.values())),
            "pais": "España",
            "provincia": ZONAS[zona],
            "zona": zona,
            "tipologia": TIPOLOGIAS[(i // len(zonas)) % len(TIPOLOGIAS)],
        })
    return pd.DataFrame(filas)


def generar_calendario(fechas: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "fecha": fechas,
        "festivo": [f.strftime("%Y-%m-%d") in FESTIVOS for f in fechas],
        "nombre_festivo": [FESTIVOS.get(f.strftime("%Y-%m-%d"), "") for f in fechas],
        "no_lectivo": [no_lectivo(f) for f in fechas],
        "evento": [EVENTOS.get(f.strftime("%Y-%m-%d"), "") for f in fechas],
    })


def generar_ventas(rest: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    fechas = pd.DatetimeIndex(cal["fecha"])
    n = len(fechas)
    doy = fechas.day_of_year.values
    dow = fechas.day_of_week.values
    estacional = 1 + 0.10 * np.sin(2 * np.pi * (doy - 100) / 365)
    t = np.arange(n) / 365
    festivo = cal["festivo"].values
    nolect = cal["no_lectivo"].values
    evento = cal["evento"].values != ""

    tablas = []
    for _, r in rest.iterrows():
        escala_local = rng.uniform(0.7, 1.4)
        crecimiento = rng.uniform(-0.02, 0.06)
        semanal = np.array(PATRON_SEMANAL[r.tipologia])[dow]
        # campañas de su marca
        en_campana = np.zeros(n, dtype=bool)
        for marca, ini, fin, _ in CAMPANAS:
            if marca == r.marca:
                en_campana |= (fechas >= ini) & (fechas <= fin)
        # eventos de su zona
        factor_zona = np.ones(n)
        for zona, f, fac, _ in EVENTOS_ZONA:
            if zona == r.zona:
                factor_zona[fechas == f] = fac

        for canal, base in CANALES.items():
            nivel = base * escala_local * (1 + crecimiento * t)
            f_fest = np.where(festivo, {"calle": 1.15, "centro_comercial": 0.60, "autopista": 1.10}[r.tipologia], 1.0)
            if canal == "delivery":
                f_fest = np.where(festivo, 1.20, 1.0)
            f_nolect = np.where(nolect, 1.08 if canal != "delivery" else 1.0, 1.0)
            f_evento = np.where(evento, 1.35 if canal == "delivery" else 0.95, 1.0)
            f_camp = np.where(en_campana, 1.18, 1.0)
            ruido = rng.lognormal(0, 0.06, n)
            tickets = nivel * semanal * estacional * f_fest * f_nolect * f_evento * f_camp * factor_zona * ruido

            tm_base = TICKET_MEDIO[r.marca] * (1.30 if canal == "delivery" else 1.0)
            ticket_medio = tm_base * (1 + 0.025 * t) * np.where(en_campana, 0.94, 1.0) * rng.lognormal(0, 0.03, n)

            tablas.append(pd.DataFrame({
                "restaurante_id": r.restaurante_id, "fecha": fechas, "canal": canal,
                "tickets": tickets, "ticket_medio": ticket_medio,
            }))
    return pd.concat(tablas, ignore_index=True)


def inyectar_anomalias(ventas: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    """Modifica 'ventas' in-place y devuelve la tabla de etiquetas."""
    fechas = pd.DatetimeIndex(cal["fecha"])
    fechas_normales = fechas[(~cal["festivo"].values) & (cal["evento"].values == "")]
    fechas_normales = fechas_normales[(fechas_normales > fechas[14]) & (fechas_normales < fechas[-14])]
    series = ventas[["restaurante_id", "canal"]].drop_duplicates().values
    etiquetas = []

    # 1) Puntuales: caída o pico de un día, en tickets o en ticket medio
    usados = set()
    while len(etiquetas) < N_PUNTUALES:
        rid, canal = series[rng.integers(len(series))]
        f = fechas_normales[rng.integers(len(fechas_normales))]
        if (rid, canal, f) in usados:
            continue
        usados.add((rid, canal, f))
        metrica = rng.choice(["tickets", "tickets", "ticket_medio"])
        if metrica == "tickets":
            factor = rng.uniform(0.35, 0.65) if rng.random() < 0.65 else rng.uniform(1.5, 2.0)
        else:
            factor = rng.uniform(0.55, 0.70) if rng.random() < 0.5 else rng.uniform(1.4, 1.7)
        m = (ventas.restaurante_id == rid) & (ventas.canal == canal) & (ventas.fecha == f)
        ventas.loc[m, metrica] *= factor
        etiquetas.append({"restaurante_id": rid, "canal": canal, "fecha": f, "tipo": "puntual",
                          "metrica": metrica, "factor": round(factor, 3)})

    # 2) Cambios de tendencia: cambio de nivel que se mantiene
    elegidas = rng.choice(len(series), N_TENDENCIAS, replace=False)
    for k in elegidas:
        rid, canal = series[k]
        f = fechas[rng.integers(120, len(fechas) - 90)]
        factor = rng.uniform(0.70, 0.82) if rng.random() < 0.7 else rng.uniform(1.18, 1.30)
        m = (ventas.restaurante_id == rid) & (ventas.canal == canal) & (ventas.fecha >= f)
        ventas.loc[m, "tickets"] *= factor
        etiquetas.append({"restaurante_id": rid, "canal": canal, "fecha": f, "tipo": "tendencia",
                          "metrica": "tickets", "factor": round(factor, 3)})
    return pd.DataFrame(etiquetas)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    fechas = pd.date_range(FECHA_INI, FECHA_FIN, freq="D")
    rest = generar_restaurantes()
    cal = generar_calendario(fechas)
    ventas = generar_ventas(rest, cal)
    etiquetas = inyectar_anomalias(ventas, cal)

    ventas["tickets"] = ventas["tickets"].round().astype(int)
    ventas["ticket_medio"] = ventas["ticket_medio"].round(2)
    ventas["ventas"] = (ventas["tickets"] * ventas["ticket_medio"]).round(2)
    ventas = ventas[["restaurante_id", "fecha", "canal", "ventas", "tickets", "ticket_medio"]]

    rest.to_csv(SALIDA / "restaurantes.csv", index=False)
    cal.to_csv(SALIDA / "calendario.csv", index=False)
    pd.DataFrame(CAMPANAS, columns=["marca", "inicio", "fin", "nombre"]).to_csv(SALIDA / "campanas.csv", index=False)
    ventas.to_csv(SALIDA / "ventas.csv", index=False)
    etiquetas.to_csv(SALIDA / "etiquetas.csv", index=False)
    print(f"Generados {len(rest)} restaurantes, {len(ventas):,} filas de ventas, "
          f"{len(etiquetas)} anomalías inyectadas en {SALIDA}")


if __name__ == "__main__":
    main()
