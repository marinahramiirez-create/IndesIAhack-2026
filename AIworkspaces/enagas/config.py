"""
Configuración del proyecto Enagás.

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
# Azure:  postgresql+psycopg://usuario:clave@servidor.postgres.database.azure.com:5432/enagas
(RAIZ / "datos").mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(RAIZ / 'datos' / 'enagas.db').as_posix()}")

# --- Datos de entrada ----------------------------------------------------
DIR_DATOS = Path(os.getenv("DIR_DATOS", RAIZ / "datos_sinteticos" / "salida"))
# Si los datos reales traen otros nombres de columna: {"archivo.csv": {"nombre_real": "nombre_interno"}}
MAPEO_COLUMNAS: dict[str, dict[str, str]] = {}

# --- LLM (opcional: solo redacta, nunca calcula) ---------------------------
LLM_PROVEEDOR = os.getenv("LLM_PROVEEDOR", "ninguno").lower()  # ninguno | azure | openai
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Criterios ESTÁNDAR actuales (iguales para todas las UM) -------------
# Valores de ejemplo: el día del reto, sustituir por los umbrales reales de Enagás.
UMBRAL_STD = {
    "dif_pcs": float(os.getenv("UMBRAL_DIF_PCS", 0.005)),          # 0,5 % PCS calculado vs cromatógrafo
    "dif_orion": float(os.getenv("UMBRAL_DIF_ORION", 0.01)),        # 1 % Neptuno vs ORION
    "dif_orion_abs_energia": float(os.getenv("UMBRAL_DIF_ORION_ABS_E", 20000)),  # kWh
    "dif_orion_abs_volumen": float(os.getenv("UMBRAL_DIF_ORION_ABS_V", 2000)),   # m3(n)
    "dif_his": float(os.getenv("UMBRAL_DIF_HIS", 0.25)),            # 25 % vs mismo día semana anterior
}

# --- Criterios ADAPTATIVOS (por UM, aprendidos de su histórico) ----------
CUANTIL_ADAPTATIVO = float(os.getenv("CUANTIL_ADAPTATIVO", 0.995))  # lo normal de cada UM = hasta su percentil 99,5
MARGEN_ADAPTATIVO = float(os.getenv("MARGEN_ADAPTATIVO", 1.25))    # se alerta al superar lo normal en un 25 %
VENTANA_HISTORICO_DIAS = 365
MIN_DIAS_HISTORICO = 60
FRECUENCIA_FLAG_HABITUAL = 0.05  # si una UM tiene MODULA/SERIE >5 % de los días, para ella es "normal"

# --- Modelo y niveles ------------------------------------------------------
FECHA_FIN_ENTRENAMIENTO = os.getenv("FECHA_FIN_ENTRENAMIENTO", "2024-10-31")
FECHA_FIN_CALIBRACION = os.getenv("FECHA_FIN_CALIBRACION", "2024-12-31")
# La "validación automática" se calibra para conservar el 93 % de los días que el usuario acabó ajustando.
# (No 98 %: la etiqueta proxy incluye modificaciones sin incidencia real, imposibles de anticipar.)
# Con datos sintéticos: misma detección que la regla estándar con ~59 % menos revisiones.
RECALL_MINIMO_AUTO = float(os.getenv("RECALL_MINIMO_AUTO", 0.93))
PRECISION_PRIORITARIA = 0.80   # en "revisión prioritaria" al menos 8 de cada 10 deben ser incidencias
