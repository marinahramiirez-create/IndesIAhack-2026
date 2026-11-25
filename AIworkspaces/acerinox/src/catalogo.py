"""
Catálogo: valores técnicos válidos + diccionario coloquial → técnico, cada traducción con su cita al catálogo.

Regla de oro (el jurado lo llama "prohibido inventar"): el asistente SOLO puede usar grados, acabados y formatos
que existan aquí. Lo que no está en el catálogo se rechaza y se explica por qué.

El día del reto: revisar el catálogo PDF real y ajustar GRADOS / ACABADOS / PROPIEDADES (la cita apunta a la sección
o página del PDF). El texto del catálogo se indexa para buscar y enseñar la evidencia (secciones()).
"""
import re
from functools import lru_cache

from rank_bm25 import BM25Okapi

import config

# Valor canónico → (sinónimos coloquiales o comerciales, sección del catálogo)
GRADOS = {
    "304": ([r"\b304\b(?!l)", r"\b1\.4301\b", r"\b18\s*/\s*8\b", r"\ba2\b"], "1.1"),
    "304L": ([r"\b304\s*l\b", r"\b1\.4307\b"], "1.2"),
    "316L": ([r"\b316\s*l?\b", r"\b1\.4404\b", r"\ba4\b"], "1.3"),
    "430": ([r"\b430\b", r"\b1\.4016\b"], "1.4"),
    "441": ([r"\b441\b", r"\b1\.4509\b"], "1.5"),
    "2205": ([r"\b2205\b", r"\b1\.4462\b", r"d[uú]plex"], "1.6"),
}
ACABADOS = {   # el orden importa: "brillo espejo" debe ser espejo, no BA
    "espejo": ([r"espejo", r"\bn[ºo°]?\s*8\b", r"\b2p\b", r"pulido especular"], "2.6"),
    "satinado": ([r"satinad", r"cepillad", r"scotch", r"\bn[ºo°]?\s*4\b", r"\b2j\b"], "2.5"),
    "BA": ([r"\bba\b", r"\b2r\b", r"brillante", r"\bbrillo\b", r"reflectante"], "2.4"),
    "2B": ([r"\b2b\b", r"semibrillante", r"\best[aá]ndar\b", r"\bliso\b"], "2.3"),
    "1D": ([r"\b1d\b", r"laminad[oa] en caliente", r"\bnegro\b"], "2.1"),
    "2D": ([r"\b2d\b", r"\bmate\b"], "2.2"),
}
FORMATOS = {
    "fleje": ([r"\bflejes?\b", r"\btiras?\b", r"\bbandas?\b"], "3.2"),
    "bobina": ([r"\bbobinas?\b", r"\brollos?\b", r"\bcoils?\b"], "3.1"),
    "chapa": ([r"\bchapas?\b", r"\bhojas?\b", r"\bplanchas?\b", r"\bplacas?\b", r"\bl[aá]minas?\b"], "3.3"),
}
ESPESORES_CATALOGO = [0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0]

# Propiedad pedida con palabras de cliente → grados que la cumplen según el catálogo
PROPIEDADES = [
    (r"\bmar\b|marin|costa|salitre|clorur|piscina|agua salada|offshore|desaliniz", ["316L", "2205"],
     "resistencia a cloruros / ambiente marino", "1.3, 1.6"),
    (r"escape|alta temperatura|calor|horno|quemador", ["441"], "resistencia a alta temperatura", "1.5"),
    (r"magn[eé]tic|im[aá]n", ["430", "441"], "magnético (ferrítico)", "1.4, 1.5"),
    (r"barat|econ[oó]mic|low cost", ["430"], "económico (sin níquel)", "1.4"),
    (r"alimentari|alimentos|cocina|menaje", ["304", "316L"], "apto para alimentos", "1.1, 1.3"),
    (r"muy resistente|alta resistencia mec|estructural", ["2205"], "alta resistencia mecánica", "1.6"),
    (r"soldar|soldad|soldable", ["304L", "316L"], "bajo carbono para soldadura", "1.2, 1.3"),
]

# Peticiones que el catálogo no puede respaldar → se rechazan con explicación (no se inventan "aceros mágicos")
NO_RESPALDADO = [
    (r"m[aá]gic|milagr", "no existe un acero «mágico»"),
    (r"no se raye nunca|irrayable|indestructible|irrompible", "ningún acero del catálogo es irrayable o indestructible"),
    (r"no se oxide nunca|nunca se oxida|oxidaci[oó]n cero", "ningún inoxidable garantiza cero corrosión en cualquier medio"),
    (r"transparente|que flote|ligero como", "propiedad física que no tiene ningún acero del catálogo"),
]
# Grados con pinta de acero pero que no están en el catálogo (904L, 321, 310S, 201...)
PATRON_GRADO_DESCONOCIDO = re.compile(r"\b(?:aisi\s*)?([1-9]\d{2}[a-z]?|2[0-9]{3})\b", re.I)


def cita(seccion: str) -> str:
    return f"Catálogo §{seccion}"


def valores_validos() -> dict:
    return {"grado": list(GRADOS), "acabado": list(ACABADOS), "formato": list(FORMATOS),
            "espesores": ESPESORES_CATALOGO}


# ---------------------------------------------------------------- texto del catálogo (evidencia)
def _texto_catalogo() -> str:
    ruta = config.DIR_DATOS / config.CATALOGO
    if ruta.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(f"\n## Página {i}\n" + (p.extract_text() or "") for i, p in enumerate(PdfReader(ruta).pages, 1))
    return ruta.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def secciones() -> list[dict]:
    """Trozos del catálogo por encabezado (### o ## Página n) para citar y buscar."""
    salida, actual = [], None
    for linea in _texto_catalogo().splitlines():
        m = re.match(r"^#{2,3}\s+(.*)", linea)
        if m:
            titulo = m.group(1).strip()
            num = re.match(r"^([\d.]+|Página \d+)", titulo)
            actual = {"seccion": num.group(1).rstrip(".") if num else titulo, "titulo": titulo, "texto": ""}
            salida.append(actual)
        elif actual is not None and linea.strip():
            actual["texto"] += linea.strip() + " "
    return salida


def texto_seccion(sec: str) -> str:
    for s in secciones():
        if s["seccion"] == sec:
            return f"{s['titulo']}: {s['texto'].strip()}"
    return ""


@lru_cache(maxsize=1)
def _bm25():
    return BM25Okapi([re.findall(r"\w+", (s["titulo"] + " " + s["texto"]).lower()) for s in secciones()])


def buscar(consulta: str, k: int = 3) -> list[dict]:
    scores = _bm25().get_scores(re.findall(r"\w+", consulta.lower()))
    orden = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return [secciones()[i] for i in orden if scores[i] > 0]
