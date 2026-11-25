"""
Texto OFICIAL en español de Part-IS (no es una traducción nuestra).

Las reglas IS.I.OR están en el anexo II del Reglamento de Ejecución (UE) 2023/203, publicado en el
Diario Oficial de la UE en todas las lenguas oficiales; la versión española es igual de auténtica que la inglesa.
Las Easy Access Rules de EASA (de donde sale normativa/clausulas.json) solo existen en inglés, así que:
  - para BUSCAR y JUZGAR se sigue usando el inglés (el documento de requisitos está en inglés),
  - para ENSEÑAR la norma en la app se usa este texto oficial en español, citando la fuente.

Descarga (canal oficial para máquinas de la Oficina de Publicaciones de la UE, CELLAR):
    curl -L -H "Accept: application/xhtml+xml" -H "Accept-Language: spa" -o normativa/reg_2023_203_es.xhtml ^
         http://publications.europa.eu/resource/celex/32023R0203
Uso:
    python -m src.normativa_es normativa/reg_2023_203_es.xhtml     # genera normativa/clausulas_es.json
"""
import html
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import config

RUTA = config.RAIZ / "normativa" / "clausulas_es.json"
FUENTE = ("Texto oficial en español del Reglamento de Ejecución (UE) 2023/203, anexo II (Part-IS), "
          "DO L 31 de 2.2.2023 · obtenido de la Oficina de Publicaciones de la UE (EUR-Lex). "
          "Versión publicada originalmente: no incluye posibles modificaciones posteriores.")
URL_EURLEX = "https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32023R0203"


def _texto(fragmento_html: str) -> list[str]:
    """HTML del DOUE → líneas de texto (cada fila de tabla = una línea: "a) La organización...")."""
    t = re.sub(r"</(p|tr|div|li)>", "\n", fragmento_html)
    t = re.sub(r"</td>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    lineas = [re.sub(r"\s+", " ", x).strip() for x in t.split("\n")]
    salida = []
    for x in lineas:
        if not x:
            continue
        # el DOUE separa la letra/número de su texto en celdas distintas: "a)" + "La organización..." → una línea
        if salida and re.fullmatch(r"\(?[a-z0-9ivx]{1,4}\)", salida[-1]):
            salida[-1] = salida[-1] + " " + x
        else:
            salida.append(x)
    return salida


def parsear(ruta: Path) -> dict:
    s = ruta.read_text(encoding="utf-8")
    # encabezados del articulado: <p class="oj-ti-grseq-1"><span class="oj-bold">IS.I.OR.205 Título</span></p>
    cabeceras = list(re.finditer(r'<p[^>]*class="oj-ti-grseq-1"[^>]*>\s*<span[^>]*>\s*(IS\.[A-Z]\.OR\.\d{3})\s+([^<]+)</span>', s))
    clausulas = {}
    for i, m in enumerate(cabeceras):
        fin = cabeceras[i + 1].start() if i + 1 < len(cabeceras) else len(s)
        trozo = s[m.end():fin]
        corte = re.search(r'<p[^>]*class="oj-(ti-section|doc-ti|ti-grseq-1)"', trozo)   # fin de la parte
        if corte:
            trozo = trozo[:corte.start()]
        lineas = _texto(trozo)
        apartados, actual = {}, None
        for x in lineas:
            mm = re.match(r"^\(?([a-z])\)\s*(.*)", x)
            siguiente = chr(ord(actual) + 1) if actual else "a"
            if mm and mm.group(1) == siguiente:   # solo la letra que toca: "i)" o "v)" sueltos son incisos romanos
                actual = mm.group(1)
                apartados[actual] = mm.group(2)
            elif actual:
                apartados[actual] += "\n" + x
        clausulas[m.group(1)] = {"titulo": html.unescape(m.group(2)).strip(), "texto": "\n".join(lineas),
                                 "apartados": apartados}
    return clausulas


@lru_cache(maxsize=1)
def cargar() -> dict:
    return json.loads(RUTA.read_text(encoding="utf-8")) if RUTA.exists() else {}


def texto_obligacion(clausula: str, apartado: str) -> str | None:
    """
    Texto oficial en español de la parte citada de la cláusula.
      "(a)(4)"  → solo el punto 4) del apartado a)
      "(a)-(b)" / "(g)-(i)" → apartados a) a b) / g) a i)
      "(c)(1)-(2)" → apartado c) completo
    """
    c = cargar().get("clausulas", {}).get(clausula)
    if not c:
        return None
    letras = re.findall(r"\(([a-z])\)", apartado)
    if len(letras) == 2 and "-" in apartado and re.fullmatch(r"\([a-z]\)-\([a-z]\)", apartado):
        letras = [chr(x) for x in range(ord(letras[0]), ord(letras[1]) + 1)]
    partes = [c["apartados"][l] for l in letras if l in c["apartados"]]
    if not partes:
        return c["texto"]
    m = re.fullmatch(r"\(([a-z])\)\((\d+)\)", apartado)     # un único punto numerado
    if m:
        for linea in partes[0].split("\n"):
            if re.match(rf"^\(?{m.group(2)}\)\s", linea):
                return f"{m.group(1)}) … {linea}"
    return "\n".join(f"{l}) {p}" for l, p in zip(letras, partes))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cl = parsear(Path(sys.argv[1]))
    RUTA.write_text(json.dumps({"fuente": FUENTE, "url": URL_EURLEX, "clausulas": cl}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"{len(cl)} cláusulas en español → {RUTA}")
    print("IDs:", ", ".join(cl))
