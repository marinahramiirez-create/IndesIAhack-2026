"""
Base de datos del proyecto Acerinox. SQLite local / PostgreSQL Azure (solo cambia DATABASE_URL en .env).

Tablas:
  stock          inventario (se carga desde el CSV; el día del reto puede ser la BD real)
  peticiones     cada petición atendida: texto, ficha interpretada, acción y bulto propuesto
                 → "demanda no atendida" (lo que se pidió y no había) para compras/producción
"""
import json
from datetime import datetime

import pandas as pd
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, insert, inspect, text

import config

engine = create_engine(config.DATABASE_URL, future=True)
metadata = MetaData()

peticiones = Table(
    "peticiones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha_hora", DateTime, nullable=False),
    Column("texto", Text),
    Column("ficha", Text),            # JSON
    Column("accion", String(20)),     # buscar | repreguntar | rechazar
    Column("resultado", String(20)),  # exacto | transformable | sin_stock | —
    Column("bulto", String(40)),
)


def inicializar():
    metadata.create_all(engine)


def guardar_df(df: pd.DataFrame, tabla: str):
    df.to_sql(tabla, engine, if_exists="replace", index=False)


def leer_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params=params or {})


def existe_tabla(nombre: str) -> bool:
    return inspect(engine).has_table(nombre)


def registrar_peticion(texto: str, ficha: dict, accion: str, resultado: str, bulto: str = ""):
    inicializar()
    with engine.begin() as con:
        con.execute(insert(peticiones).values(fecha_hora=datetime.now(), texto=texto,
                                              ficha=json.dumps(ficha, ensure_ascii=False, default=str),
                                              accion=accion, resultado=resultado, bulto=bulto))
