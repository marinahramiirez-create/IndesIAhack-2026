"""
Percepción (nivel 4): transcribe los PDF escaneados con un modelo con visión → texto con tablas en filas,
para que el resto del pipeline sea idéntico al de un documento digital (guía §7, "Percepción").
Se guarda en caché por huella del fichero: transcribir es lo más caro y no se repite.
"""
import hashlib
import json
from pathlib import Path

import pymupdf
from pydantic import BaseModel

from src import llm

CACHE = Path(__file__).resolve().parent.parent / "cache" / "transcripciones"

SISTEMA = """Eres un transcriptor de documentos escaneados. Transcribe la página EXACTAMENTE como está escrita,
en español, sin resumir, sin corregir y sin añadir nada. Las cifras, fechas e identificadores deben copiarse
carácter a carácter (un error en una cifra produce un falso hallazgo).
- Conserva los títulos tal cual, incluidos "Tabla N. ..." y "Figura N. ...".
- Las tablas, una fila por línea con las celdas separadas por " | ", empezando por la fila de cabecera.
- Si en la portada hay una tabla "Documento / Versión", transcríbela como líneas "Documento" y el valor debajo,
  "Versión" y el valor debajo.
- Si algo es ilegible, escribe [ilegible].
Devuelve JSON: {"texto": "<transcripción de la página>"}"""


class Pagina(BaseModel):
    texto: str


def _huella(ruta: Path) -> str:
    return hashlib.sha1(ruta.read_bytes()).hexdigest()[:16]


def transcribir(ruta: str | Path, modelo: str = llm.MODELO_AUDITOR) -> list[str]:
    ruta = Path(ruta)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{ruta.stem}_{_huella(ruta)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    pdf = pymupdf.open(ruta)
    paginas = []
    for p in pdf:
        png = p.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
        r, _ = llm.pedir_json(SISTEMA, [llm.imagen(png), {"type": "text", "text": "Transcribe esta página."}],
                              Pagina, modelo=modelo, max_tokens=8000)
        paginas.append(r.texto)
    cache.write_text(json.dumps(paginas, ensure_ascii=False, indent=1), encoding="utf-8")
    return paginas
