"""
Base de datos del proyecto RBE.

Con SQLAlchemy el mismo código funciona en SQLite (local) y en PostgreSQL (Azure).
Solo cambia DATABASE_URL en el .env.

Tablas:
  alertas         resultado del detector (se reescribe en cada ejecución del pipeline)
  serie_esperada  real vs esperado por día (para los gráficos)
  metricas        F1, precisión, ruido filtrado...
  decisiones      lo que decide el humano (aprobar / descartar). NUNCA se borra.
"""
from datetime import datetime

import pandas as pd
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, insert, text

import config

engine = create_engine(config.DATABASE_URL, future=True)
metadata = MetaData()

decisiones = Table(
    "decisiones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("alerta_id", String(120), nullable=False, index=True),
    Column("decision", String(20), nullable=False),  # aprobada | descartada
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
    from sqlalchemy import inspect
    return inspect(engine).has_table(nombre)


def registrar_decision(alerta_id: str, decision: str, comentario: str = "", usuario: str = "analista"):
    inicializar()
    with engine.begin() as con:
        con.execute(insert(decisiones).values(
            alerta_id=alerta_id, decision=decision, comentario=comentario,
            usuario=usuario, fecha_hora=datetime.now(),
        ))


def ultimas_decisiones() -> pd.DataFrame:
    """Última decisión por alerta."""
    inicializar()
    df = leer_df("SELECT * FROM decisiones ORDER BY fecha_hora")
    if df.empty:
        return df
    return df.groupby("alerta_id").tail(1)
