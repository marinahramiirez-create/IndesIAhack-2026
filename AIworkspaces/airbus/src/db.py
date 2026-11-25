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
  usuarios         quién puede entrar en la app: cuentas locales (usuario + contraseña) y cuentas
                   Microsoft Entra ID (ver AUTENTICACION.md y src/auth.py).
"""
import uuid
from datetime import datetime

import pandas as pd
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, insert, inspect, select, text, update)

import config

engine = create_engine(config.DATABASE_URL, future=True)
metadata = MetaData()

# Identificador interno propio (UUID) que NO depende de Microsoft. Una persona puede tener a la vez
# cuenta local (login + password_hash) y cuenta Microsoft (entra_tid + entra_oid) en la MISMA fila,
# así sus decisiones no cambian de dueño al pasar de una a otra.
# Microsoft identifica a una persona de forma estable por (tid = inquilino, oid = objeto). El correo/UPN
# puede cambiar, por eso NO se usa como clave.
usuarios = Table(
    "usuarios", metadata,
    Column("id", String(36), primary_key=True),                 # UUID interno (texto: vale en SQLite y PostgreSQL)
    Column("login", String(80), unique=True),                   # nombre de usuario para entrar con contraseña
    Column("password_hash", String(200)),                       # PBKDF2 (nunca la contraseña); vacío = sin acceso local
    Column("nombre", String(120), nullable=False),
    Column("email", String(254)),                               # UPN / correo; informativo, puede cambiar
    Column("rol", String(20), nullable=False, default="revisor"),  # revisor | auditor | admin (= App Roles de Entra)
    Column("activo", Boolean, nullable=False, default=True),
    Column("proveedor", String(20), nullable=False, default="local"),  # local | entra (cómo se creó)
    Column("entra_tid", String(36)),                            # claim "tid" del token de Microsoft
    Column("entra_oid", String(36)),                            # claim "oid" del token de Microsoft
    Column("creado", DateTime, nullable=False),
    Column("ultimo_acceso", DateTime),
    UniqueConstraint("entra_tid", "entra_oid", name="uq_usuarios_entra"),
)

USUARIO_LOCAL = "revisor"   # usuario por defecto si el inicio de sesión está desactivado (AUTH_ACTIVADA=false)

decisiones = Table(
    "decisiones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("req_id", String(60), nullable=False, index=True),
    Column("decision", String(20), nullable=False),        # aprobado | corregido
    Column("veredicto_final", String(20)),                 # Cumple | No cumple | Revisar | No aplica
    Column("comentario", Text),
    Column("usuario", String(80)),                         # nombre visible (se mantiene por compatibilidad)
    Column("usuario_id", String(36), ForeignKey("usuarios.id"), index=True),  # quién decidió (auditoría)
    Column("fecha_hora", DateTime, nullable=False),
)


def _columnas(tabla: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(tabla)}


def inicializar():
    """Crea las tablas que falten y actualiza BD antiguas sin borrar datos."""
    metadata.create_all(engine)
    # 'usuarios' creada por una versión anterior sin login/contraseña
    existentes = _columnas("usuarios")
    for col, tipo in {"login": "VARCHAR(80)", "password_hash": "VARCHAR(200)"}.items():
        if col not in existentes:
            with engine.begin() as con:
                con.execute(text(f"ALTER TABLE usuarios ADD COLUMN {col} {tipo}"))
    # 'decisiones' creada antes de existir 'usuarios'
    if "usuario_id" not in _columnas("decisiones"):
        with engine.begin() as con:
            con.execute(text("ALTER TABLE decisiones ADD COLUMN usuario_id VARCHAR(36) REFERENCES usuarios(id)"))
            nombres = [r[0] for r in con.execute(text("SELECT DISTINCT COALESCE(usuario, :u) FROM decisiones"),
                                                 {"u": USUARIO_LOCAL})]
        # Las decisiones antiguas se asignan a un usuario local con su mismo nombre
        for nombre in nombres:
            uid = obtener_usuario_local(nombre)
            with engine.begin() as con:
                con.execute(text("UPDATE decisiones SET usuario_id = :id "
                                 "WHERE usuario_id IS NULL AND COALESCE(usuario, :u) = :n"),
                            {"id": uid, "u": USUARIO_LOCAL, "n": nombre})


# --------------------------------------------------------------------------- usuarios
def _fila(where) -> dict | None:
    with engine.connect() as con:
        r = con.execute(select(usuarios).where(where)).mappings().first()
    return dict(r) if r else None


def buscar_por_login(login: str) -> dict | None:
    return _fila(usuarios.c.login == login.strip().lower())


def buscar_por_id(usuario_id: str) -> dict | None:
    return _fila(usuarios.c.id == usuario_id)


def crear_usuario_local(login: str, nombre: str, password_hash: str, rol: str = "revisor",
                        email: str | None = None) -> str:
    nuevo = str(uuid.uuid4())
    with engine.begin() as con:
        con.execute(insert(usuarios).values(id=nuevo, login=login.strip().lower(), password_hash=password_hash,
                                            nombre=nombre, email=email, rol=rol, activo=True,
                                            proveedor="local", creado=datetime.now()))
    return nuevo


def cambiar_password(usuario_id: str, password_hash: str):
    with engine.begin() as con:
        con.execute(update(usuarios).where(usuarios.c.id == usuario_id).values(password_hash=password_hash))


def obtener_o_crear_usuario_entra(tid: str, oid: str, nombre: str, email: str | None, rol: str | None) -> dict:
    """Usuario que entra con Microsoft. Se identifica SIEMPRE por (tid, oid).
    Si aún no existe pero hay una cuenta local con el mismo correo, se vincula a ella (mismas decisiones)."""
    ahora = datetime.now()
    with engine.begin() as con:
        fila = con.execute(select(usuarios.c.id).where(usuarios.c.entra_tid == tid,
                                                       usuarios.c.entra_oid == oid)).first()
        if not fila and email:
            fila = con.execute(select(usuarios.c.id).where(usuarios.c.entra_oid.is_(None),
                                                           usuarios.c.email == email.lower())).first()
        cambios = {"nombre": nombre, "email": (email or "").lower() or None, "entra_tid": tid, "entra_oid": oid,
                   "ultimo_acceso": ahora}
        if rol:                                    # el rol manda Entra ID (App Roles) cuando viene en el token
            cambios["rol"] = rol
        if fila:
            con.execute(update(usuarios).where(usuarios.c.id == fila[0]).values(**cambios))
            uid = fila[0]
        else:
            uid = str(uuid.uuid4())
            con.execute(insert(usuarios).values(id=uid, activo=True, proveedor="entra", creado=ahora,
                                                **{"rol": "revisor", **cambios}))
    return buscar_por_id(uid)


def marcar_acceso(usuario_id: str):
    with engine.begin() as con:
        con.execute(update(usuarios).where(usuarios.c.id == usuario_id).values(ultimo_acceso=datetime.now()))


def obtener_usuario_local(nombre: str = USUARIO_LOCAL) -> str:
    """Id del usuario local con ese nombre (sin contraseña); lo crea si no existe.
    Se usa con el inicio de sesión desactivado y para asignar decisiones antiguas."""
    with engine.begin() as con:
        fila = con.execute(select(usuarios.c.id).where(usuarios.c.proveedor == "local",
                                                       usuarios.c.nombre == nombre)).first()
        if fila:
            return fila[0]
        nuevo = str(uuid.uuid4())
        con.execute(insert(usuarios).values(id=nuevo, nombre=nombre, rol="revisor", activo=True,
                                            proveedor="local", creado=datetime.now()))
        return nuevo


# --------------------------------------------------------------------------- resultados
def guardar_df(df: pd.DataFrame, tabla: str):
    df.to_sql(tabla, engine, if_exists="replace", index=False)


def leer_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params=params or {})


def existe_tabla(nombre: str) -> bool:
    return inspect(engine).has_table(nombre)


def registrar_decision(req_id: str, decision: str, veredicto_final: str, comentario: str = "",
                       usuario: str = USUARIO_LOCAL, usuario_id: str | None = None):
    """usuario_id: el del usuario que ha iniciado sesión. Sin sesión, se usa el usuario local."""
    inicializar()
    usuario_id = usuario_id or obtener_usuario_local(usuario)
    with engine.begin() as con:
        con.execute(insert(decisiones).values(req_id=req_id, decision=decision, veredicto_final=veredicto_final,
                                              comentario=comentario, usuario=usuario, usuario_id=usuario_id,
                                              fecha_hora=datetime.now()))


def ultimas_decisiones() -> pd.DataFrame:
    inicializar()
    df = leer_df("SELECT * FROM decisiones ORDER BY fecha_hora")
    return df.groupby("req_id").tail(1) if not df.empty else df
