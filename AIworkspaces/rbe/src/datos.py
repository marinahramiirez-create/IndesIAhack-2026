"""
Carga de datos de entrada.

Hoy lee los CSV sintéticos. El día del reto, si los datos reales vienen con otro formato,
SOLO hay que tocar este archivo (o config.MAPEO_COLUMNAS); el resto del código no cambia.
"""
import pandas as pd

import config

COLUMNAS_VENTAS = ["restaurante_id", "fecha", "canal", "ventas", "tickets", "ticket_medio"]
COLUMNAS_RESTAURANTES = ["restaurante_id", "marca", "pais", "provincia", "zona", "tipologia"]


def _leer(nombre: str, obligatorio: bool = True) -> pd.DataFrame | None:
    ruta = config.DIR_DATOS / nombre
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(
                f"No encuentro {ruta}. Genera datos con: python datos_sinteticos/generar.py "
                f"o pon DIR_DATOS en el .env"
            )
        return None
    df = pd.read_csv(ruta)
    return df.rename(columns=config.MAPEO_COLUMNAS)


def cargar() -> dict[str, pd.DataFrame | None]:
    ventas = _leer("ventas.csv")
    ventas["fecha"] = pd.to_datetime(ventas["fecha"])
    faltan = set(COLUMNAS_VENTAS) - {"ticket_medio"} - set(ventas.columns)
    if faltan:
        raise ValueError(f"A ventas.csv le faltan columnas: {faltan}. Añádelas a MAPEO_COLUMNAS en config.py")
    if "ticket_medio" not in ventas or ventas["ticket_medio"].isna().all():
        # si no viene, se calcula: ticket medio = ventas / tickets
        ventas["ticket_medio"] = ventas["ventas"] / ventas["tickets"].replace(0, pd.NA)

    restaurantes = _leer("restaurantes.csv")
    calendario = _leer("calendario.csv", obligatorio=False)
    if calendario is not None:
        calendario["fecha"] = pd.to_datetime(calendario["fecha"])
    campanas = _leer("campanas.csv", obligatorio=False)
    etiquetas = _leer("etiquetas.csv", obligatorio=False)  # solo existe con datos sintéticos
    if etiquetas is not None:
        etiquetas["fecha"] = pd.to_datetime(etiquetas["fecha"])
    return {"ventas": ventas, "restaurantes": restaurantes, "calendario": calendario,
            "campanas": campanas, "etiquetas": etiquetas}
