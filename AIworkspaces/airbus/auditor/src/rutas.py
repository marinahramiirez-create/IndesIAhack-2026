"""
Dónde está el corpus NIMBUS en cada ordenador (git no lo sube: cada uno lo tiene en local).

Orden de búsqueda (vale la primera carpeta que tenga PDF dentro):
  1. Variable CORPUS_NIMBUS del .env (ruta a la carpeta con los PDF).
  2. 03_corpus_trabajo_NIMBUS en la carpeta del auditor o en cualquiera de sus carpetas padre
     (la raíz del repositorio, donde lo pide el README). Sirve tanto si el zip se descomprimió
     con doble carpeta (03_.../03_...) como con una sola.
  3. Documents/Airbus_datos/03_corpus_trabajo_NIMBUS del usuario.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
NOMBRE = "03_corpus_trabajo_NIMBUS"


def candidatos() -> list[Path]:
    c = []
    if os.getenv("CORPUS_NIMBUS"):
        c.append(Path(os.getenv("CORPUS_NIMBUS")))
    for base in [RAIZ, *RAIZ.parents, Path.home() / "Documents" / "Airbus_datos"]:
        c += [base / NOMBRE / NOMBRE, base / NOMBRE]
    return c


def tiene_pdf(p: Path) -> bool:
    try:
        return p.is_dir() and next(p.rglob("*.pdf"), None) is not None
    except OSError:
        return False


def buscar_corpus() -> Path | None:
    return next((p for p in candidatos() if tiene_pdf(p)), None)


def ayuda_corpus() -> str:
    """Mensaje en español para cuando no se encuentran los PDF."""
    raiz_repo = RAIZ.parents[2] if len(RAIZ.parents) > 2 else RAIZ
    return ("\nNo encuentro los PDF del corpus NIMBUS.\n"
            f"  → Descomprime 03_corpus_trabajo_NIMBUS.zip dentro de:\n      {raiz_repo}\n"
            "    (al lado de la carpeta AIworkspaces).\n"
            "  → O escribe en el archivo .env la ruta de la carpeta con los PDF:\n"
            "      CORPUS_NIMBUS=C:\\ruta\\a\\03_corpus_trabajo_NIMBUS\n")


CORPUS = buscar_corpus() or (RAIZ.parents[2] / NOMBRE / NOMBRE)
