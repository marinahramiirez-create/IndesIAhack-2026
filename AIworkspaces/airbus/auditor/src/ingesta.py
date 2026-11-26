"""
Ingesta: PDF → datos estructurados de un documento NIMBUS.

Para cada PDF se obtiene:
  - codigo y version (portada: "Documento <código>", "Versión <n>")
  - paginas: texto por página
  - unidades: cada elemento con identificador propio (requisito, fila de registro, riesgo, directriz...),
    con su texto, página y la cláusula Part-IS que cita (si la cita)
  - tablas y figuras: título ("Tabla 3. ...", "Figura 2. ...") y página
Nada de esto usa LLM: es determinista y se puede volver a ejecutar sin coste.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Identificadores tipo SEC-REQ-011, C2L-SEC-025, RSK-03, VUL-2026-012, PR-SEC-012...
PATRON_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]{1,8}){0,3}-\d{2,4}\b")
PATRON_CLAUSULA = re.compile(r"IS\.I\.OR\.(\d{3})")
PATRON_TITULO = re.compile(r"^(Tabla|Figura) (\d+)\.\s+(.+)$")
# Inicio de una unidad: "SEC-REQ-011 — texto" (raya, guion o dos puntos tras el ID)
PATRON_UNIDAD = re.compile(r"^(" + PATRON_ID.pattern[2:-2] + r")\s*[—–:-]\s+(.*)$")
# Pie de página repetido ("XXX v3.0 — DOCUMENTO SINTÉTICO ...", "Página 1 de 6"): no es contenido
PATRON_PIE = re.compile(r"DOCUMENTO SINTÉTICO \(IndesIAhack\)|^Página \d+ de \d+$")


@dataclass
class Unidad:
    id: str
    texto: str
    pagina: int
    clausula: str = ""          # cláusula que cita la propia unidad (IS.I.OR.xxx), si la cita
    seccion: str = ""


@dataclass
class Documento:
    ruta: str
    codigo: str
    version: str
    titulo: str
    paginas: list[str]
    unidades: list[Unidad] = field(default_factory=list)
    tablas: list[dict] = field(default_factory=list)      # {"n", "titulo", "pagina"}
    figuras: list[dict] = field(default_factory=list)     # {"n", "titulo", "pagina"}
    escaneado: bool = False

    @property
    def texto(self) -> str:
        return "\n".join(f"[página {i + 1}]\n{t}" for i, t in enumerate(self.paginas))

    def ids(self) -> set[str]:
        return {u.id for u in self.unidades}


def _portada(lineas: list[str]) -> tuple[str, str, str]:
    """Código, versión y título a partir de la tabla de la portada."""
    codigo = version = ""
    for i, l in enumerate(lineas[:60]):
        if l.strip() == "Documento" and i + 1 < len(lineas) and not codigo:
            codigo = lineas[i + 1].strip()
        if l.strip() == "Versión" and i + 1 < len(lineas) and not version:
            version = lineas[i + 1].strip()
    titulo = " ".join(l.strip() for l in lineas[:3] if l.strip())
    return codigo, version, titulo


def leer(ruta: str | Path, vision: bool = False) -> Documento:
    """vision=True: si el PDF es escaneado (sin texto digital), se transcribe con el modelo con visión."""
    pdf = pymupdf.open(ruta)
    paginas = []
    for p in pdf:
        lineas = [l for l in p.get_text().splitlines() if not PATRON_PIE.search(l.strip())]
        paginas.append("\n".join(lineas))
    caracteres = sum(len(t.strip()) for t in paginas)
    escaneado = caracteres < 200 * max(pdf.page_count, 1) and pdf.page_count > 0
    if escaneado and vision:
        from src import vision as v
        paginas = v.transcribir(ruta)
    todas = "\n".join(paginas).splitlines()
    codigo, version, titulo = _portada(todas)
    if not codigo:   # portada transcrita como "Documento: XXX" o "Documento | XXX"
        m = re.search(r"Documento\s*[:|]\s*([A-Z][A-Z0-9-]{3,})", "\n".join(todas[:80]))
        codigo = m.group(1) if m else ""
    if not version:
        m = re.search(r"Versión\s*[:|]?\s*\n?\s*(\d+\.\d+)", "\n".join(todas[:80]))
        version = m.group(1) if m else ""
    doc = Documento(str(ruta), codigo, version, titulo, paginas, escaneado=escaneado)

    seccion = ""
    actual: Unidad | None = None
    vistos_tf = set()
    for n, texto in enumerate(paginas, start=1):
        for linea in texto.splitlines():
            l = linea.strip()
            m_sec = re.match(r"^(\d+(?:\.\d+)*)\s+[A-ZÁÉÍÓÚ]", l)
            if m_sec and len(l) < 90 and not PATRON_ID.match(l):
                seccion = m_sec.group(1)
            m_t = PATRON_TITULO.match(l)
            if m_t and (m_t.group(1), m_t.group(2)) not in vistos_tf:
                vistos_tf.add((m_t.group(1), m_t.group(2)))
                destino = doc.tablas if m_t.group(1) == "Tabla" else doc.figuras
                destino.append({"n": int(m_t.group(2)), "titulo": l, "pagina": n})
            m_u = PATRON_UNIDAD.match(l)
            if m_u:
                if actual:
                    doc.unidades.append(actual)
                actual = Unidad(m_u.group(1), m_u.group(2), n, seccion=seccion)
            elif actual:
                # la unidad continúa hasta la siguiente unidad o un título de sección/tabla/figura
                if m_sec or m_t or not l:
                    doc.unidades.append(actual)
                    actual = None
                else:
                    actual.texto += " " + l
    if actual:
        doc.unidades.append(actual)
    for u in doc.unidades:
        c = PATRON_CLAUSULA.search(u.texto)
        u.clausula = f"IS.I.OR.{c.group(1)}" if c else ""
    return doc


def figura_png(doc: Documento, n_pagina: int, zoom: float = 2.0) -> bytes:
    """Imagen de una página (para que el modelo con visión lea los diagramas)."""
    pdf = pymupdf.open(doc.ruta)
    return pdf[n_pagina - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")


if __name__ == "__main__":
    import sys
    for f in sorted(Path(sys.argv[1]).glob("*.pdf")):
        d = leer(f)
        print(f"{d.codigo:22s} v{d.version:4s} pág={len(d.paginas):2d} unidades={len(d.unidades):3d} "
              f"tablas={len(d.tablas):2d} figuras={len(d.figuras)} escaneado={d.escaneado}")
