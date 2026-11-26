"""
Texto legible de una página de PDF, para el editor de versiones de la pantalla de revisión.

`page.get_text()` devuelve un renglón por línea visual: los párrafos salen partidos y las tablas celda a celda
(«C2L-SEC-» en una línea y «026» en la siguiente). Aquí se reconstruye:
  - párrafos: los renglones de un mismo bloque se juntan (si un renglón acaba en guion, sin espacio);
    las viñetas y listas numeradas empiezan línea nueva;
  - tablas: se detectan con pymupdf y se escriben fila a fila con columnas separadas por « | »;
  - orden de lectura: de arriba abajo y de izquierda a derecha;
  - se quitan los pies de página repetidos (los mismos que quita la ingesta).
Si la página no tiene texto digital (escaneado), devuelve "" y quien llama usa la transcripción.
"""
import re

import pymupdf

try:                                   # el mismo patrón de pie de página que usa la ingesta
    from src.ingesta import PATRON_PIE
except Exception:                      # pragma: no cover
    PATRON_PIE = re.compile(r"DOCUMENTO SINTÉTICO|^Página \d+ de \d+$", re.I)

VINETA = re.compile(r"^\s*(?:[•·▪◦\-–—*]|\d+[.)]|[a-z][.)])\s+")


def _celda(t) -> str:
    return " ".join(str(t or "").split())


def _celda_de(palabras: list, caja) -> str:
    """Palabras cuyo centro cae en la celda, renglón a renglón (mismo bloque y línea de pymupdf)."""
    x0, y0, x1, y1 = caja
    dentro = sorted((w for w in palabras if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1),
                    key=lambda w: (w[5], w[6], w[7]))
    lineas, clave = [], None
    for w in dentro:
        if (w[5], w[6]) != clave:
            lineas.append(w[4])
            clave = (w[5], w[6])
        else:
            lineas[-1] += " " + w[4]
    return _parrafo(lineas)


def _parrafo(lineas: list[str]) -> str:
    salida = ""
    for l in (x.strip() for x in lineas):
        if not l or PATRON_PIE.search(l):
            continue
        if not salida:
            salida = l
        elif VINETA.match(l):
            salida += "\n" + l
        elif salida.endswith("-") and len(salida) > 1 and salida[-2].isalnum():
            salida += l                # «C2L-SEC-» + «026» → «C2L-SEC-026»
        else:
            salida += " " + l
    return salida


def texto_legible(page: "pymupdf.Page") -> str:
    elementos = []                     # (y, x, texto)
    zonas = []
    try:
        # Buscar tablas es lo lento: solo se hace si la página tiene líneas o rectángulos dibujados
        tablas = page.find_tables().tables if page.get_drawings() else []
        palabras = page.get_text("words") if tablas else []      # una sola lectura de la página
        for t in tablas:
            # El texto de cada celda sale de las palabras que caen dentro de ella: t.extract() pega las
            # palabras («Bloqueodesesión…») y desordena los códigos partidos en dos renglones.
            filas = [[_celda_de(palabras, c) if c else "" for c in fila.cells] for fila in t.rows]
            filas = [f for f in filas if any(f)]
            if not filas:
                continue
            zonas.append(pymupdf.Rect(t.bbox))
            elementos.append((t.bbox[1], t.bbox[0], "\n".join(" | ".join(f) for f in filas)))
    except Exception:                  # una tabla rara no debe impedir sacar el resto del texto
        zonas = []
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt, _, tipo = b[:7]
        if tipo != 0 or not txt.strip():
            continue
        centro = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if any(centro in z for z in zonas):
            continue                   # ya está dentro de una tabla
        p = _parrafo(txt.splitlines())
        if p:
            elementos.append((y0, x0, p))
    elementos.sort(key=lambda e: (round(e[0] / 3), e[1]))
    return "\n\n".join(e[2] for e in elementos).strip()
