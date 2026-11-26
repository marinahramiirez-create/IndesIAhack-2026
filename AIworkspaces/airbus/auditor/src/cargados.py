"""
Documentos cargados desde la pantalla de revisión («Cargar archivo» en Inicio).

`procesar()` deja el documento listo para abrirlo en Revisión, igual que los del corpus:
  - PDF:     una imagen y un texto legible por página (paginas/up_<id>_<n>.jpg / .txt) y código, versión y
             título leídos de la portada con la misma ingesta que usa el auditor (sin visión, sin coste).
  - Imagen:  se enseña tal cual.
  - Word:    párrafos, títulos y tablas (contenido.json), leídos del .docx con la biblioteca estándar.
  - Excel:   cada hoja como tabla (contenido.json), leída del .xlsx con la biblioteca estándar.
  - CSV/TXT: tabla o texto (contenido.json).
El original se guarda tal cual en cargados/<id>/ para descargarlo. Nada de esto audita el documento:
los hallazgos salen de auditar.py.
"""
import csv
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ZOOM = 1.4
MAX_FILAS = 1000
MAX_COLS = 60
PATRON_CODIGO = re.compile(r"\b[A-Z]{2,5}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

TIPOS = {".pdf": "pdf", ".png": "imagen", ".jpg": "imagen", ".jpeg": "imagen", ".gif": "imagen", ".webp": "imagen",
         ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv", ".txt": "txt", ".md": "txt"}


def tipo_de(nombre: str) -> str:
    return TIPOS.get(Path(nombre).suffix.lower(), "otro")


def _codigo(*textos: str) -> str:
    for t in textos:
        m = PATRON_CODIGO.search(t or "")
        if m:
            return m.group(0)
    return ""


# ---------------------------------------------------------------- Word
def _texto_w(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t")).strip()


def leer_docx(ruta: Path) -> list[dict]:
    with zipfile.ZipFile(ruta) as z:
        raiz = ET.fromstring(z.read("word/document.xml"))
    cuerpo = raiz.find(f"{W}body")
    bloques = []
    for el in list(cuerpo) if cuerpo is not None else []:
        if el.tag == f"{W}p":
            txt = _texto_w(el)
            if not txt:
                continue
            estilo = el.find(f"{W}pPr/{W}pStyle")
            val = (estilo.get(f"{W}val") if estilo is not None else "") or ""
            bloques.append({"t": "h" if re.search(r"heading|t[ií]tulo|title", val, re.I) else "p", "x": txt})
        elif el.tag == f"{W}tbl":
            filas = [[_texto_w(c) for c in fila.findall(f"{W}tc")][:MAX_COLS] for fila in el.findall(f"{W}tr")]
            if filas:
                bloques.append({"t": "tabla", "filas": filas[:MAX_FILAS]})
    return bloques


# ---------------------------------------------------------------- Excel
def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def leer_xlsx(ruta: Path) -> list[dict]:
    with zipfile.ZipFile(ruta) as z:
        nombres = set(z.namelist())
        compartidas = []
        if "xl/sharedStrings.xml" in nombres:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{X}si"):
                compartidas.append("".join(t.text or "" for t in si.iter(f"{X}t")))
        libro = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in nombres:
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                rels[r.get("Id")] = r.get("Target", "")
        hojas = []
        for h in libro.iter(f"{X}sheet"):
            destino = rels.get(h.get(R_ID), "")
            ruta_h = "xl/" + destino.lstrip("/").removeprefix("xl/") if destino else ""
            if ruta_h not in nombres:
                continue
            filas = []
            for fila in ET.fromstring(z.read(ruta_h)).iter(f"{X}row"):
                celdas = {}
                for c in fila.findall(f"{X}c"):
                    v, t = c.find(f"{X}v"), c.get("t")
                    if t == "s" and v is not None:
                        val = compartidas[int(v.text)] if v.text and int(v.text) < len(compartidas) else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{X}t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    if c.get("r"):
                        celdas[_col(c.get("r"))] = val
                if celdas:
                    filas.append([celdas.get(i, "") for i in range(min(max(celdas) + 1, MAX_COLS))])
                if len(filas) >= MAX_FILAS:
                    break
            hojas.append({"t": "hoja", "nombre": h.get("name", f"Hoja {len(hojas) + 1}"), "filas": filas})
    return hojas


# ---------------------------------------------------------------- CSV / texto
def _decodificar(datos: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            continue
    return datos.decode("utf-8", "replace")


def leer_csv(ruta: Path) -> list[dict]:
    texto = _decodificar(ruta.read_bytes())
    try:
        dialecto = csv.Sniffer().sniff(texto[:5000], delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel
    filas = [f[:MAX_COLS] for _, f in zip(range(MAX_FILAS), csv.reader(io.StringIO(texto), dialecto))]
    return [{"t": "hoja", "nombre": ruta.name, "filas": filas}]


def leer_txt(ruta: Path) -> list[dict]:
    return [{"t": "p", "x": p.strip()} for p in re.split(r"\n\s*\n", _decodificar(ruta.read_bytes())) if p.strip()]


def _texto_de(bloques: list[dict]) -> str:
    partes = []
    for b in bloques:
        if b["t"] in ("h", "p"):
            partes.append(b["x"])
        else:
            partes += [" | ".join(f) for f in b["filas"][:20]]
    return "\n".join(partes)


# ---------------------------------------------------------------- PDF
def _procesar_pdf(original: Path, cid: str, web: Path) -> dict:
    import pymupdf
    from src.texto_paginas import texto_legible
    pdf = pymupdf.open(original)
    (web / "paginas").mkdir(parents=True, exist_ok=True)
    textos = []
    for n, pag in enumerate(pdf, 1):
        (web / "paginas" / f"up_{cid}_{n}.jpg").write_bytes(
            pag.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).tobytes("jpg", jpg_quality=72))
        t = texto_legible(pag)
        textos.append(t)
        (web / "paginas" / f"up_{cid}_{n}.txt").write_text(t, encoding="utf-8")
    codigo = version = titulo = ""
    try:                                   # portada con la misma lógica que el auditor
        from src import ingesta
        d = ingesta.leer(original, vision=False)
        codigo, version, titulo = d.codigo, d.version, re.sub(r"\s*Documento$", "", (d.titulo or "").strip())
    except Exception:
        pass
    escaneado = sum(len(t.strip()) for t in textos) < 200 * max(pdf.page_count, 1)
    return {"vista": "pdf", "paginas": pdf.page_count, "codigo": codigo or _codigo(original.stem, *textos[:2]),
            "version": version, "titulo": titulo, "escaneado": escaneado}


def procesar(original: Path, cid: str, web: Path) -> dict:
    """Prepara un documento cargado. Devuelve {vista, paginas, codigo, version, titulo, escaneado}."""
    tipo = tipo_de(original.name)
    if tipo == "pdf":
        return _procesar_pdf(original, cid, web)
    if tipo == "imagen":
        return {"vista": "imagen", "paginas": 1, "codigo": _codigo(original.stem), "version": "", "titulo": "",
                "escaneado": False}
    lector = {"docx": leer_docx, "xlsx": leer_xlsx, "csv": leer_csv, "txt": leer_txt}.get(tipo)
    bloques = []
    if lector:
        try:
            bloques = lector(original)
        except Exception as e:             # archivo dañado o con un formato raro: se guarda igual, sin vista
            bloques = [{"t": "p", "x": f"No se pudo leer el contenido ({type(e).__name__}). Descárgalo para abrirlo."}]
    (web / "cargados" / cid).mkdir(parents=True, exist_ok=True)
    (web / "cargados" / cid / "contenido.json").write_text(json.dumps(bloques, ensure_ascii=False), encoding="utf-8")
    texto = _texto_de(bloques)
    titulo = next((b["x"] for b in bloques if b["t"] in ("h", "p")), "")[:160]
    return {"vista": "contenido" if lector else "descarga", "paginas": 1, "codigo": _codigo(original.stem, texto[:3000]),
            "version": "", "titulo": titulo, "escaneado": False}
