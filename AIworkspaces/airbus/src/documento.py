"""
Extractor: documento técnico → lista de requisitos estructurados.

Admite .docx, .pdf, .md y .txt. Busca los IDs con config.PATRON_ID_REQUISITO (REQ-001, SR-12...).
Cada requisito guarda de dónde sale (documento + página o párrafo) → trazabilidad.

El día del reto: si el documento real usa otro formato de ID, cambiar PATRON_ID_REQUISITO en el .env.
Si los requisitos vienen en una tabla Excel/CSV, basta con devolver la misma estructura desde aquí.
"""
import re
from pathlib import Path

import config


def _bloques_docx(ruta: Path):
    from docx import Document
    doc = Document(ruta)
    seccion = ""
    for i, p in enumerate(doc.paragraphs, start=1):
        t = p.text.strip()
        if not t:
            continue
        if p.style.name.lower().startswith("heading"):
            seccion = t
        yield t, seccion, f"párrafo {i}"
    for ti, tabla in enumerate(doc.tables, start=1):   # requisitos en tablas (muy habitual)
        for fi, fila in enumerate(tabla.rows, start=1):
            yield " ".join(c.text.strip() for c in fila.cells), seccion, f"tabla {ti}, fila {fi}"


def _bloques_pdf(ruta: Path):
    from pypdf import PdfReader
    for n, pag in enumerate(PdfReader(ruta).pages, start=1):
        for linea in (pag.extract_text() or "").split("\n"):
            if linea.strip():
                yield linea.strip(), "", f"página {n}"


def _bloques_texto(ruta: Path):
    seccion = ""
    for i, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
        t = linea.strip()
        if t.startswith("#"):
            seccion = t.lstrip("# ")
            continue
        if t:
            yield t.replace("**", ""), seccion, f"línea {i}"


def extraer(ruta: Path | None = None) -> list[dict]:
    ruta = Path(ruta or config.DIR_DATOS / config.DOCUMENTO)
    lector = {".docx": _bloques_docx, ".pdf": _bloques_pdf}.get(ruta.suffix.lower(), _bloques_texto)
    patron = re.compile(config.PATRON_ID_REQUISITO)

    requisitos, actual = [], None
    for texto, seccion, ubicacion in lector(ruta):
        m = patron.search(texto)
        if m and m.start() < 15:        # el ID abre el párrafo → empieza un requisito nuevo
            actual = {"req_id": m.group(0), "texto": texto[m.end():].strip(" :.-–\t"),
                      "seccion": seccion, "documento": ruta.name, "ubicacion": ubicacion}
            requisitos.append(actual)
        elif actual is not None and not texto[:1].isdigit() and len(texto) > 0 and ubicacion.startswith("página"):
            actual["texto"] += " " + texto    # en PDF un requisito puede ocupar varias líneas
    vistos = {}
    for r in requisitos:                   # si un ID se repite, se queda el primero
        vistos.setdefault(r["req_id"], r)
    return list(vistos.values())


if __name__ == "__main__":
    for r in extraer():
        print(r["req_id"], "|", r["ubicacion"], "|", r["texto"][:90])
