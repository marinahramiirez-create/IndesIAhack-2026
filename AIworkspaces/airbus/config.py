"""
Configuración del proyecto Airbus (auditoría de cumplimiento normativo).

Todo lo que cambia entre "local" y "Azure" se lee del archivo .env.
La lógica del proyecto NO se toca: solo se cambia el .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")

# --- Base de datos -------------------------------------------------------
(RAIZ / "datos").mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(RAIZ / 'datos' / 'airbus.db').as_posix()}")

# --- Entradas ------------------------------------------------------------
# Normativa EASA ya troceada por cláusula (se genera con: python -m src.normativa archivo.xml)
RUTA_CLAUSULAS = Path(os.getenv("RUTA_CLAUSULAS", RAIZ / "normativa" / "clausulas.json"))
# Documento a auditar (.docx, .pdf, .md o .txt con IDs tipo REQ-001) y gold set (.csv)
DIR_DATOS = Path(os.getenv("DIR_DATOS", RAIZ / "datos_sinteticos" / "salida"))
DOCUMENTO = os.getenv("DOCUMENTO", "documento_requisitos.docx")
GOLD = os.getenv("GOLD", "gold.csv")
# Patrón de los IDs de requisito en el documento. Cambiar si el documento real usa otro (p. ej. "SYS-REQ-0001").
PATRON_ID_REQUISITO = os.getenv("PATRON_ID_REQUISITO", r"\b(?:REQ|SR|SEC|IS)-\d{2,4}\b")

# --- LLM -----------------------------------------------------------------
# ninguno | azure | openai     (con "ninguno" funciona el auditor por reglas, sin IA generativa)
LLM_PROVEEDOR = os.getenv("LLM_PROVEEDOR", "ninguno").lower()
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Parámetros de la auditoría ------------------------------------------
TOP_K = int(os.getenv("TOP_K", 4))                         # cláusulas recuperadas por requisito
JUICIOS_AUTOCONSISTENCIA = int(os.getenv("JUICIOS_AUTOCONSISTENCIA", 3))  # juicios LLM por requisito
UMBRAL_CONFIANZA = float(os.getenv("UMBRAL_CONFIANZA", 0.6))   # por debajo → bucle de reflexión / "Revisar"
MAX_REFLEXIONES = int(os.getenv("MAX_REFLEXIONES", 1))
