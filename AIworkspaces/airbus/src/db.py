"""
Base de datos del proyecto Airbus. SQLite local / PostgreSQL Azure (solo cambia DATABASE_URL en .env).

Tablas:
  hallazgos        un veredicto por requisito (se reescribe en cada ejecución)
  contradicciones  pares de requisitos incoherentes
  homogeneidad     requisitos con detalle insuficiente
  cobertura        reglas IR de Part-IS y qué requisitos las cubren
  metricas         F1, trazabilidad... (clave → JSON)
  traza            pasos de los agentes
  decisiones       lo que decide el revisor (aprobar / corregir). NUNCA se borra.
"""
from datetime import datetime

import pandas as pd
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, insert, inspect, text

import config

engine = create_engine(config.DATABASE_URL, future=True)
metadata = MetaData()

decisiones = Table(
    "decisiones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("req_id", String(60), nullable=False, index=True),
    Column("decision", String(20), nullable=False),        # aprobado | corregido
    Column("veredicto_final", String(20)),                 # Cumple | No cumple | Revisar | No aplica
    Column("comentario", Text),
    Column("usuario", String(80)),
    Column("fecha_hora", DateTime, nullable=False),
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


def registrar_decision(req_id: str, decision: str, veredicto_final: str, comentario: str = "", usuario: str = "revisor"):
    inicializar()
    with engine.begin() as con:
        con.execute(insert(decisiones).values(req_id=req_id, decision=decision, veredicto_final=veredicto_final,
                                              comentario=comentario, usuario=usuario, fecha_hora=datetime.now()))


def ultimas_decisiones() -> pd.DataFrame:
    inicializar()
    df = leer_df("SELECT * FROM decisiones ORDER BY fecha_hora")
    return df.groupby("req_id").tail(1) if not df.empty else df
