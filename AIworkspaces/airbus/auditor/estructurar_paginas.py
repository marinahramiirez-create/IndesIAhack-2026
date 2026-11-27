"""
Genera la estructura (títulos, párrafos y tablas) de cada página para el editor de versiones, SIN llamar a la IA.

    .venv/bin/python estructurar_paginas.py          (Windows: .\\.venv\\Scripts\\python estructurar_paginas.py)

Lee los documentos de salidas/revision/index.html (ya generado) y escribe salidas/revision/paginas/<doc>_<n>.html
junto a la imagen y el .txt de cada página. generar_revision.py también lo hace; este script sirve para crearlos
sin volver a leer el corpus con visión. Las páginas escaneadas no tienen texto y se quedan solo con su .txt.
"""
import json
import re
import sys
from pathlib import Path

import pymupdf

from src.estructura import pagina_html
from src.rutas import CORPUS, ayuda_corpus
WEB = Path(__file__).resolve().parent / "salidas" / "revision"


def main():
    linea = next((l for l in (WEB / "index.html").read_text(encoding="utf-8").splitlines() if l.startswith("const D=")), None)
    if not linea:
        sys.exit("Primero genera la pantalla: python generar_revision.py")
    docs = json.loads(linea[len("const D="):-1])["docs"]
    pdfs = list(CORPUS.rglob("*.pdf"))
    if not pdfs:
        sys.exit(ayuda_corpus())
    hechas = 0
    for cod, info in docs.items():
        f = next((p for p in pdfs if re.search(r"(^|_)" + re.escape(cod) + r"(_|$)", p.stem)), None)
        if f is None:                           # el nombre del archivo no lleva el código: se busca en su texto
            f = next((p for p in pdfs if cod in pymupdf.open(p)[0].get_text()[:3000]), None)
        if f is None:
            print(f"  aviso: no encuentro el PDF de {cod}")
            continue
        for n, pag in enumerate(pymupdf.open(f), 1):
            html = pagina_html(pag)
            if html:
                (WEB / "paginas" / f"{info['slug']}_{n}.html").write_text(html, encoding="utf-8")
                hechas += 1
    print(f"{hechas} páginas con estructura → {WEB / 'paginas'}")


if __name__ == "__main__":
    main()
