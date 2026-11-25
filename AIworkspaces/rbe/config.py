"""
Configuración del proyecto RBE.

Todo lo que cambia entre "local" y "Azure" se lee del archivo .env.
La lógica del proyecto NO se toca: solo se cambia el .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")

# --- Base de datos -------------------------------------------------------
# Local:  sqlite (un archivo, no hay que instalar nada)
# Azure:  postgresql+psycopg://usuario:clave@servidor.postgres.database.azure.com:5432/rbe
(RAIZ / "datos").mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(RAIZ / 'datos' / 'rbe.db').as_posix()}")

# --- Datos de entrada ----------------------------------------------------
# Carpeta con ventas.csv, restaurantes.csv, calendario.csv, campanas.csv
# El día del reto: apuntar a la carpeta con los datos reales.
DIR_DATOS = Path(os.getenv("DIR_DATOS", RAIZ / "datos_sinteticos" / "salida"))

# Si los datos reales traen otros nombres de columna, se traducen aquí
# (nombre_real -> nombre_interno). Ejemplo: {"id_local": "restaurante_id"}
MAPEO_COLUMNAS: dict[str, str] = {}

# --- LLM (opcional: solo redacta, nunca calcula) ---------------------------
# ninguno | azure | openai
LLM_PROVEEDOR = os.getenv("LLM_PROVEEDOR", "ninguno").lower()
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")  # nombre del despliegue del modelo
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Parámetros de detección ---------------------------------------------
SEMANAS_BASE = int(os.getenv("SEMANAS_BASE", 6))  # semanas previas para el patrón esperado
# Una alerta puntual exige las DOS cosas: ser estadísticamente rara (z) y relevante para el negocio (%).
# Calibrados con las anomalías sintéticas (F1 ≈ 0,86). Con datos reales: recalibrar (ver README).
UMBRAL_Z_PUNTUAL = float(os.getenv("UMBRAL_Z_PUNTUAL", 5.0))   # z robusto mínimo
UMBRAL_DESVIACION_MIN = float(os.getenv("UMBRAL_DESVIACION_MIN", 0.25))  # 25 % sobre lo esperado
UMBRAL_CAMBIO_TENDENCIA = float(os.getenv("UMBRAL_CAMBIO_TENDENCIA", 0.10))  # 10 % de cambio de nivel
TOLERANCIA_DIAS_PUNTUAL = 1    # para evaluar F1
TOLERANCIA_DIAS_TENDENCIA = 21
