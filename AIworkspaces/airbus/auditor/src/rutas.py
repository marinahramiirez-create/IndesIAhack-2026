"""
Dónde está el corpus NIMBUS en cada ordenador (git no lo sube: cada uno lo tiene en local).

Orden de búsqueda:
  1. Variable CORPUS_NIMBUS del .env (ruta a la carpeta con los PDF).
  2. 03_corpus_trabajo_NIMBUS en la raíz del repositorio del equipo (donde lo pide el README).
  3. Documents/Airbus_datos/03_corpus_trabajo_NIMBUS del usuario.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
_SUB = Path("03_corpus_trabajo_NIMBUS") / "03_corpus_trabajo_NIMBUS"


def _candidatos():
    if os.getenv("CORPUS_NIMBUS"):
        yield Path(os.getenv("CORPUS_NIMBUS"))
    for base in [RAIZ, *RAIZ.parents]:
        yield base / _SUB
    yield Path.home() / "Documents" / "Airbus_datos" / _SUB


CORPUS = next((p for p in _candidatos() if p.is_dir()), RAIZ.parents[2] / _SUB)
