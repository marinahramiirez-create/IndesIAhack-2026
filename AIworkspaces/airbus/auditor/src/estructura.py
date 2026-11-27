"""
Estructura de una página de PDF en HTML sencillo (títulos, párrafos y tablas) para el editor de versiones.

Solo usa PyMuPDF (sin IA): las tablas salen de page.find_tables() y el texto de cada celda se lee por su zona
(get_textbox), que respeta guiones y puntos («2026-10-12», «S. Gallardo»). Los títulos se deducen del tamaño de
letra frente al del cuerpo del texto. Una página escaneada no tiene texto: devuelve "" y el editor usa el .txt.
"""
from collections import Counter
from html import escape

import pymupdf


def _texto(t: str) -> str:
    return " ".join(t.split())


def _tabla(page, tab) -> str:
    filas = []
    for i, row in enumerate(tab.rows):
        celdas, cells = [], list(row.cells)
        j = 0
        while j < len(cells):
            c = cells[j]
            if c is None:                       # celda absorbida por una combinada anterior
                j += 1
                continue
            span = 1
            while j + span < len(cells) and cells[j + span] is None:
                span += 1
            tag = "th" if i == 0 else "td"
            lineas = [escape(_texto(l)) for l in page.get_textbox(pymupdf.Rect(c)).splitlines() if l.strip()]
            extra = ' colspan="%d"' % span if span > 1 else ""
            celdas.append("<%s%s>%s</%s>" % (tag, extra, "<br>".join(lineas), tag))
            j += span
        if celdas:
            filas.append("<tr>" + "".join(celdas) + "</tr>")
    return "<table>" + "".join(filas) + "</table>" if filas else ""


def pagina_html(page) -> str:
    try:
        tablas = page.find_tables().tables
    except Exception:                          # PDF raro: se sigue sin tablas
        tablas = []
    zonas = [pymupdf.Rect(t.bbox) for t in tablas]
    piezas = [(t.bbox[1], t.bbox[0], _tabla(page, t)) for t in tablas]

    bloques = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
    tam = Counter()
    for b in bloques:
        for l in b["lines"]:
            for s in l["spans"]:
                tam[round(s["size"], 1)] += len(s["text"].strip())
    cuerpo = tam.most_common(1)[0][0] if tam else 10

    for b in bloques:
        r = pymupdf.Rect(b["bbox"])
        if any((r & z).get_area() > 0.5 * max(r.get_area(), 1) for z in zonas):   # «&» no modifica r (intersect sí)
            continue                           # ese texto ya está en una tabla
        texto = _texto(" ".join("".join(s["text"] for s in l["spans"]) for l in b["lines"]))
        if not texto:
            continue
        spans = [s for l in b["lines"] for s in l["spans"] if s["text"].strip()]
        grande = max(s["size"] for s in spans)
        negrita = all(s["flags"] & 16 or "Bold" in s["font"] for s in spans)
        if grande >= cuerpo * 1.45:
            tag = "h2"
        elif (grande >= cuerpo * 1.15 or negrita) and len(texto) < 140:
            tag = "h3"
        else:
            tag = "p"
        piezas.append((b["bbox"][1], b["bbox"][0], f"<{tag}>{escape(texto)}</{tag}>"))

    piezas.sort(key=lambda x: (round(x[0]), x[1]))
    return "\n".join(h for _, _, h in piezas if h)
