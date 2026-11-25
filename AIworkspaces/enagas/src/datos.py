"""
Carga de las 5 fuentes y cruce en una tabla UM × día.

Hoy lee los CSV sintéticos. El día del reto, si los datos reales vienen con otro formato,
SOLO hay que tocar este archivo (o config.MAPEO_COLUMNAS); el resto del código no cambia.
"""
import pandas as pd

import config


def _leer(nombre: str, obligatorio: bool = True) -> pd.DataFrame | None:
    ruta = config.DIR_DATOS / nombre
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"No encuentro {ruta}. Genera datos con: python datos_sinteticos/generar.py "
                                    f"o pon DIR_DATOS en el .env")
        return None
    df = pd.read_csv(ruta, keep_default_na=True)
    df = df.rename(columns=config.MAPEO_COLUMNAS.get(nombre, {}))
    if "fecha" in df:
        df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def cargar() -> dict[str, pd.DataFrame | None]:
    return {
        "um": _leer("um.csv"),
        "neptuno": _leer("neptuno.csv"),
        "slm": _leer("slm.csv"),
        "orion": _leer("orion.csv"),
        "calidad_gas": _leer("calidad_gas.csv"),
        "contrastacion": _leer("contrastacion.csv", obligatorio=False),
        "etiquetas": _leer("etiquetas.csv", obligatorio=False),  # solo con datos sintéticos
    }


def tabla_um_dia(d: dict) -> pd.DataFrame:
    """Una fila por UM y día con el dato de cada fuente lado a lado (trazabilidad: columna = fuente)."""
    nep = d["neptuno"].rename(columns={"volumen_normalizado": "vol_neptuno", "energia": "ene_neptuno",
                                       "pcs_calculado": "pcs_calculado", "estado": "estado_neptuno"})
    slm = d["slm"].rename(columns={"volumen_normalizado": "vol_slm", "energia": "ene_slm"})
    ori = d["orion"].rename(columns={"volumen_normalizado": "vol_orion", "energia": "ene_orion"})
    cal = d["calidad_gas"].rename(columns={"pcs": "pcs_cromatografo"})

    df = slm.merge(nep, on=["um_id", "fecha"], how="left")
    df = df.merge(ori, on=["um_id", "fecha"], how="left")
    df = df.merge(d["um"], on="um_id", how="left")
    df = df.merge(cal, on=["cromatografo_id", "fecha"], how="left")
    df["ajuste_tipo"] = df["ajuste_tipo"].fillna("")
    df["estado_neptuno"] = df["estado_neptuno"].fillna("NC")
    return df.sort_values(["um_id", "fecha"]).reset_index(drop=True)
