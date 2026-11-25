"""
Configuración del proyecto Acerinox (asistente de inventario por voz y texto).

Todo lo que cambia entre "local" y "Azure" se lee del archivo .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")

# --- Base de datos (stock + conversaciones + demanda no atendida) ---------
(RAIZ / "datos").mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(RAIZ / 'datos' / 'acerinox.db').as_posix()}")

# --- Entradas ------------------------------------------------------------
DIR_DATOS = Path(os.getenv("DIR_DATOS", RAIZ / "datos_sinteticos" / "salida"))
STOCK = os.getenv("STOCK", "stock.csv")                         # el día del reto: export de la BD de stock
CATALOGO = os.getenv("CATALOGO", "catalogo.md")                 # .md, .txt o .pdf
REGLAS = os.getenv("REGLAS", "reglas_transformacion.txt")
CASOS = os.getenv("CASOS", "casos_prueba.csv")
# Si el stock real trae otros nombres de columna: nombre_real -> nombre_interno
MAPEO_COLUMNAS: dict[str, str] = {}

# --- LLM y voz ---------------------------------------------------------
LLM_PROVEEDOR = os.getenv("LLM_PROVEEDOR", "ninguno").lower()   # ninguno | azure | openai
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_WHISPER = os.getenv("AZURE_OPENAI_WHISPER", "")    # despliegue de transcripción (voz → texto)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Reglas de negocio ---------------------------------------------------
TOLERANCIA_ESPESOR_MM = float(os.getenv("TOLERANCIA_ESPESOR_MM", 0.02))
FACTOR_BULTO_GRANDE = float(os.getenv("FACTOR_BULTO_GRANDE", 3.0))  # bulto > 3× lo pedido = "romper un bulto grande"
MAX_PROPUESTAS = int(os.getenv("MAX_PROPUESTAS", 3))
