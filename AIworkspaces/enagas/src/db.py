"""
Base de datos del proyecto Enagás.

Con SQLAlchemy el mismo código funciona en SQLite (local) y en PostgreSQL (Azure).
Solo cambia DATABASE_URL en el .env.

Tablas:
  um_dia      criterios, umbrales propios, score de riesgo, nivel y explicación por UM y día
  metricas    comparativa regla estándar vs adaptativa vs modelo
  decisiones  lo que decide el equipo DLC (validar / regularizar / escalar). NUNCA se borra:
              es la base del "aprendizaje continuo" (las decisiones realimentan el modelo).
"""
from datetime import datetime

import pandas as pd
from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, Table, Text, create_engine, insert, inspect, text

import config

engine = create_engine(config.DATABASE_URL, future=True)
metadata = MetaData()

decisiones = Table(
    "decisiones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("um_id", String(40), nullable=False, index=True),
    Column("fecha", Date, nullable=False),
    Column("decision", String(20), nullable=False),  # validada | regularizar | escalada
    Column("nivel_sugerido", String(40)),
    Column("comentario", Text),
    Column("usuario", String(80)),
    Column("fecha_hora", DateTime, nullable=False),
)


def inicializar():
    metadata.create_all(engine)


def guardar_df(df: pd.DataFrame, tabla: str):
    df.to_sql(tabla, engine, if_exists="replace", index=False, chunksize=5000)


def leer_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params=params or {})


def existe_tabla(nombre: str) -> bool:
    return inspect(engine).has_table(nombre)


def registrar_decision(um_id: str, fecha, decision: str, nivel_sugerido: str, comentario: str = "",
                       usuario: str = "DLC"):
    inicializar()
    with engine.begin() as con:
        con.execute(insert(decisiones).values(
            um_id=um_id, fecha=pd.Timestamp(fecha).date(), decision=decision, nivel_sugerido=nivel_sugerido,
            comentario=comentario, usuario=usuario, fecha_hora=datetime.now()))


def decisiones_del_dia(fecha) -> pd.DataFrame:
    inicializar()
    df = leer_df("SELECT * FROM decisiones ORDER BY fecha_hora")
    if df.empty:
        return df
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df[df["fecha"] == pd.Timestamp(fecha)]
    return df.groupby("um_id").tail(1)
