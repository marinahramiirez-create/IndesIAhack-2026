"""
Mide respuestas.csv con el PUNTUADOR OFICIAL del kit de desarrollo (no se copia: se ejecuta el original).

    python -m nimbus.puntuar respuestas.csv

La ruta del kit se lee de NIMBUS_KIT en .env (por defecto, la carpeta del kit junto al proyecto). El kit NO se sube
a git (incluye la clave de respuestas).
"""
import os
import runpy
import sys
from pathlib import Path

import config  # noqa: F401  (carga .env)

KIT = Path(os.getenv("NIMBUS_KIT", Path(__file__).resolve().parents[3] / "06_kit_desarrollo_equipos" / "06_kit_desarrollo_equipos"))

if __name__ == "__main__":
    respuestas = sys.argv[1] if len(sys.argv) > 1 else "respuestas.csv"
    clave, punt = KIT / "clave_desarrollo.csv", KIT / "puntuar.py"
    if not punt.exists():
        sys.exit(f"No encuentro el kit en {KIT}. Pon NIMBUS_KIT=ruta/al/kit en .env")
    sys.argv = [str(punt), str(clave), respuestas] + sys.argv[2:]
    runpy.run_path(str(punt), run_name="__main__")
