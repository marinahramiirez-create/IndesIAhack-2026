"""
Ingesta: PDF → Documento (nimbus/modelos.py). Genérica: no hay nada escrito para un documento concreto.

  - Texto por página (pypdf, rápido) para prosa, secciones y requisitos.
  - Tablas reconstruidas con las COORDENADAS de cada palabra (pdfplumber): las columnas salen de la
    posición de la cabecera y las filas de la separación vertical. Así una celda partida en dos líneas
    no se convierte en dos filas.
  - Figuras: el pie "Figura N." + el recorte de la imagen, listo para un modelo de visión.
  - Escaneados (sin texto digital): se marcan para la capa de visión (nivel 4).

Caché: el resultado se guarda por huella del PDF (nimbus/cache/). Un documento que no cambia no se reprocesa.
"""
import hashlib
import json
import logging
import os
import re
import statistics
from dataclasses import asdict
from pathlib import Path

from nimbus.modelos import Documento, Figura, Requisito, Seccion, Tabla

logging.getLogger("pdfminer").setLevel(logging.ERROR)   # avisos internos de fuentes, sin interés

CACHE = Path(__file__).resolve().parent / "cache"
VERSION_INGESTA = "1"          # cambiarla invalida la caché

LIGADURAS = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
RE_PIE = re.compile(r"DOCUMENTO SINTÉTICO|^Página \d+ de \d+$")
RE_CLAUSULA = re.compile(r"IS\.I\.OR\.(\d{3})")
RE_REQ = re.compile(r"(?m)^((?:[A-Z0-9]{2,4}-SEC-\d{3})|(?:SEC-REQ-\d{3}))\s+[—–-]\s+")
RE_SECCION = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+([A-ZÁÉÍÓÚÑ¿][^\n]{2,110})$")
RE_ID_FILA = re.compile(r"^(?:[A-Z]{1,4}(?:-[A-Z0-9]{1,4})*-\d{2,4}|(?:u|adm)[\w-]*\d+|adm-turno-\w+)$")


def _limpia(t: str) -> str:
    for a, b in LIGADURAS.items():
        t = t.replace(a, b)
    return t


def _une_ids(t: str) -> str:
    """'C2L-SEC-\\n026' → 'C2L-SEC-026' (los PDF parten los identificadores al final de la línea)."""
    return re.sub(r"(?<=[A-Z0-9])-\n(?=[A-Z0-9])", "-", t)


def _clausulas(texto: str) -> list[str]:
    """'IS.I.OR.205 / .210' → ['IS.I.OR.205', 'IS.I.OR.210']"""
    salida = [f"IS.I.OR.{n}" for n in RE_CLAUSULA.findall(texto)]
    salida += [f"IS.I.OR.{n}" for n in re.findall(r"/\s*\.(\d{3})", texto)]
    return list(dict.fromkeys(salida))


# ---------------------------------------------------------------- texto, metadatos y secciones
def _texto_paginas(ruta: Path) -> list[str]:
    from pypdf import PdfReader
    paginas = []
    for p in PdfReader(ruta).pages:
        lineas = [l for l in _limpia(p.extract_text() or "").splitlines() if not RE_PIE.search(l.strip())]
        paginas.append("\n".join(lineas))
    return paginas


def _codigo(texto1: str, ruta: Path) -> str:
    m = re.search(r"Documento\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)", _une_ids(texto1))
    if m:
        return m.group(1)
    m = re.match(r"Doc_\d+_([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)_", ruta.name)   # escaneados: el nombre del fichero
    return m.group(1) if m else ruta.stem


def _secciones(paginas: list[str]) -> list[tuple[int, int, Seccion]]:
    """[(pagina, offset_en_texto_total, Seccion)] en orden de aparición."""
    salida, offset = [], 0
    for n, pag in enumerate(paginas, 1):
        for linea in pag.splitlines(keepends=True):
            m = RE_SECCION.match(linea.strip())
            if m and not re.search(r"\d{4}-\d{2}-\d{2}", linea) and len(m.group(1).split(".")) <= 3 \
                    and not re.match(r"^[\d\s.,/%-]+$", m.group(2)):
                salida.append((n, offset, Seccion(m.group(1), m.group(2).strip(), _clausulas(m.group(2)), n)))
            offset += len(linea)
        offset += 1
    return salida


def _seccion_en(secs, offset: int) -> str:
    actual = ""
    for _, off, s in secs:
        if off > offset:
            break
        actual = s.numero
    return actual


# ---------------------------------------------------------------- requisitos
def _requisitos(texto: str, paginas_off: list[int], secs) -> list[Requisito]:
    texto = _une_ids(texto)
    marcas = list(RE_REQ.finditer(texto))
    salida = []
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        cuerpo = texto[m.end():fin]
        # el requisito termina en su línea de metadatos "Verif.: ...". Lo que sigue (títulos, tablas) no es suyo
        corte = re.search(r"Verif\.\s*:\s*[^\n]*?\.(?:\s|$)", cuerpo)
        if corte:
            cuerpo = cuerpo[:corte.end()]
        plano = re.sub(r"\s+", " ", cuerpo).strip()
        tipo = re.search(r"Tipo:\s*([^·]+?)\s*·", plano)
        clau = re.search(r"·\s*(IS\.I\.OR\.\d{3}|—)\s*·", plano)
        verif = re.search(r"Verif\.\s*:\s*(.+?)\.?$", plano)
        enunciado = re.split(r"\s*Tipo:\s", plano)[0]
        pagina = sum(1 for o in paginas_off if o <= m.start())
        salida.append(Requisito(m.group(1), enunciado, tipo.group(1).strip() if tipo else "",
                                clau.group(1) if clau else "", verif.group(1).strip() if verif else "",
                                _seccion_en(secs, m.start()), pagina))
    return salida


# ---------------------------------------------------------------- tablas por coordenadas
def _lineas_pagina(pagina) -> list[dict]:
    palabras = pagina.extract_words(keep_blank_chars=False, x_tolerance=1.5, y_tolerance=2)
    lineas: list[dict] = []
    for w in sorted(palabras, key=lambda w: (round(w["top"]), w["x0"])):
        w["text"] = _limpia(w["text"])
        if lineas and abs(lineas[-1]["top"] - w["top"]) <= 2.5:
            lineas[-1]["palabras"].append(w)
        else:
            lineas.append({"top": w["top"], "bottom": w["bottom"], "palabras": [w]})
    for l in lineas:
        l["palabras"].sort(key=lambda w: w["x0"])
        l["texto"] = " ".join(w["text"] for w in l["palabras"])
        l["bottom"] = max(w["bottom"] for w in l["palabras"])
    return [l for l in lineas if not RE_PIE.search(l["texto"])]


# Título de sección que corta una tabla: "8. Matriz…" o "6.2 Gestión…" (las filas "1 Solicitud…" no llevan punto)
RE_TITULO = re.compile(r"^(?:\d{1,2}\.\s+|\d{1,2}\.\d{1,2}\.?\s+)[A-ZÁÉÍÓÚÑ][a-záéíóúñ]")
RE_INICIO_ID = re.compile(r"^(?:[A-Z][A-Z0-9]{0,4}-(?:[A-Z0-9]{1,4}-?)*\d{0,4}|(?:u|adm)[\w-]*\d+|adm-turno)")


def _columnas(cabecera: list[dict]) -> list[tuple[float, str]]:
    """
    Columnas a partir de la cabecera (1 o 2 líneas): cada columna es un intervalo horizontal; las palabras
    que se solapan (o casi) en horizontal pertenecen a la misma columna aunque estén en líneas distintas.
    """
    palabras = sorted((w for l in cabecera for w in l["palabras"]), key=lambda w: w["x0"])
    grupos = []
    for w in palabras:
        if grupos and w["x0"] <= grupos[-1]["x1"] + 6:
            grupos[-1]["x1"] = max(grupos[-1]["x1"], w["x1"])
            grupos[-1]["ws"].append(w)
        else:
            grupos.append({"x0": w["x0"], "x1": w["x1"], "ws": [w]})
    return [(g["x0"], " ".join(x["text"] for x in sorted(g["ws"], key=lambda w: (round(w["top"]), w["x0"]))))
            for g in grupos]


def _celdas(linea: dict, cols: list[tuple[float, str]]) -> list[str]:
    celdas = [""] * len(cols)
    for w in linea["palabras"]:
        idx = max([i for i, (x, _) in enumerate(cols) if w["x0"] >= x - 3] or [0])
        celdas[idx] = (celdas[idx] + " " + w["text"]).strip()
    return celdas


def _cabecera(lineas: list[dict], i: int) -> int:
    """Nº de líneas de cabecera a partir de i: 2 si la segunda está pegada y no parece una fila de datos."""
    if i + 1 < len(lineas) and lineas[i + 1]["top"] - lineas[i]["top"] < 16 and not re.search(r"\d", lineas[i + 1]["texto"]):
        return 2
    return 1


def _tablas(ruta: Path) -> list[tuple[Tabla, int]]:
    import pdfplumber
    tablas, abierta, pendiente = [], None, None
    with pdfplumber.open(ruta) as pdf:
        for n, pagina in enumerate(pdf.pages, 1):
            lineas = _lineas_pagina(pagina)
            i = 0
            if pendiente and lineas:        # el título "Tabla N." quedó al final de la página anterior
                lineas.insert(0, {"top": lineas[0]["top"] - 20, "bottom": lineas[0]["top"] - 10, "palabras": [],
                                  "texto": pendiente})
                pendiente = None
            while i < len(lineas):
                l = lineas[i]
                m = re.match(r"^Tabla (\d+)\.\s+(\S.*)", l["texto"])     # con título: "…en la Tabla 3." no es un pie
                if m and i + 1 >= len(lineas):
                    pendiente = l["texto"]
                    break
                continua = abierta and l["texto"] == abierta["cab_texto"]       # cabecera repetida en página nueva
                if m or continua:
                    if m:
                        ncab = _cabecera(lineas, i + 1)
                        cols = _columnas(lineas[i + 1:i + 1 + ncab])
                        abierta = {"tabla": Tabla(m.group(1), m.group(2).strip(), "", n, [c for _, c in cols], []),
                                   "cols": cols, "cab_texto": lineas[i + 1]["texto"]}
                        tablas.append((abierta["tabla"], n))
                        j = i + 1 + ncab
                    else:
                        j = i + 1
                    cuerpo = []
                    while j < len(lineas):
                        t = lineas[j]["texto"]
                        if re.match(r"^(Tabla|Figura) \d+\.\s+\S", t) or RE_TITULO.match(t):
                            break
                        cuerpo.append(lineas[j])
                        j += 1
                    _filas(cuerpo, abierta)
                    i = j
                    continue
                i += 1
    return tablas


def _filas(cuerpo: list[dict], abierta: dict):
    """
    Agrupa líneas en filas. Si la tabla tiene una columna de identificadores (VUL-…, C2L-SEC-…, RSK-…),
    una fila nueva empieza SOLO cuando esa columna empieza un ID nuevo: así un ID partido en dos líneas
    ("C2L-SEC-" / "026") sigue siendo una sola fila. Si no hay IDs, se usa la separación vertical.
    """
    if not cuerpo:
        return
    huecos = [b["top"] - a["top"] for a, b in zip(cuerpo, cuerpo[1:])]
    tipico = statistics.median(huecos) if huecos else 12
    todas = [_celdas(l, abierta["cols"]) for l in cuerpo]
    cuenta = [sum(1 for c in todas if c[k] and RE_INICIO_ID.match(c[k])) for k in range(len(abierta["cols"]))]
    ancla = max(range(len(cuenta)), key=lambda k: (cuenta[k], -k)) if cuenta and max(cuenta) >= 2 else None
    filas = abierta["tabla"].filas
    previa = None
    for k, linea in enumerate(cuerpo):
        celdas = todas[k]
        hueco = linea["top"] - cuerpo[k - 1]["top"] if k else None
        if hueco is not None and hueco > 3 * max(tipico, 8):
            break                                   # fin de la tabla: empieza otro bloque de texto
        if previa is None:
            nueva = True
        elif any(c.count("(") > c.count(")") for c in previa):
            nueva = False                           # un paréntesis abierto: la celda continúa en esta línea
        elif ancla is not None:
            a = celdas[ancla]
            nueva = bool(a) and bool(RE_INICIO_ID.match(a)) and not previa[ancla].endswith("-")
        else:
            nueva = bool(celdas[0]) and sum(1 for c in celdas if c) >= 2 and hueco >= 0.8 * tipico
        if nueva:
            filas.append(celdas)
            previa = celdas
        else:
            for c, v in enumerate(celdas):
                if v:
                    previa[c] = (previa[c] + " " + v).strip()
    # segunda línea de cabecera que quedó como fila: sin primera celda y sin cifras → se une a la cabecera
    if filas and not filas[0][0] and not re.search(r"\d", " ".join(filas[0])):
        cab = abierta["tabla"].cabecera
        abierta["tabla"].cabecera = [(c + " " + v).strip() for c, v in zip(cab, filas[0])]
        filas = filas[1:]
    # quita filas vacías y une IDs partidos "C2L-SEC- 026"
    abierta["tabla"].filas = [[re.sub(r"(?<=[A-Z0-9])- (?=[A-Z0-9])", "-", c) for c in f] for f in filas if any(f)]


def _figuras(ruta: Path, paginas: list[str]) -> list[tuple[Figura, int]]:
    import pdfplumber
    salida = []
    with pdfplumber.open(ruta) as pdf:
        for n, pag in enumerate(paginas, 1):
            for m in re.finditer(r"(?m)^Figura (\d+)\.\s*(.*)$", pag):
                p = pdf.pages[n - 1]
                cap = next((l for l in _lineas_pagina(p) if l["texto"].startswith(f"Figura {m.group(1)}.")), None)
                imgs = [im for im in p.images if cap is None or im["bottom"] <= cap["top"] + 5]
                im = max(imgs, key=lambda x: x["bottom"]) if imgs else None
                bbox = (im["x0"], im["top"], im["x1"], im["bottom"]) if im else ()
                salida.append((Figura(m.group(1), m.group(2).strip(), "", n, bbox), n))
    return salida


# ---------------------------------------------------------------- API
def ingerir(ruta: Path, familia: str = "") -> Documento:
    ruta = Path(os.path.abspath(ruta))   # sin "..\\": Windows limita las rutas a 260 caracteres
    huella = hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]
    cache = CACHE / f"{huella}_{VERSION_INGESTA}.json"
    if cache.exists():
        return _desde_json(json.loads(cache.read_text(encoding="utf-8")))

    paginas = _texto_paginas(ruta)
    total = sum(len(p.strip()) for p in paginas)
    doc = Documento(archivo=ruta.name, codigo=_codigo(paginas[0] if paginas else "", ruta), version="",
                    familia=familia or ruta.parent.name, paginas=len(paginas), escaneado=total < 50 * len(paginas))
    if not doc.escaneado:
        texto = "\n".join(paginas)
        doc.texto = texto
        v = re.search(r"Versión\s+(\d+(?:\.\d+)?)", texto)
        doc.version = v.group(1) if v else ""
        offs, o = [], 0
        for p in paginas:
            offs.append(o)
            o += len(p) + 1
        secs = _secciones(paginas)
        doc.secciones = [s for _, _, s in secs]
        doc.requisitos = _requisitos(texto, offs, secs)
        try:
            for t, n in _tablas(ruta):
                pos = texto.find(f"Tabla {t.numero}.")
                t.seccion = _seccion_en(secs, pos) if pos >= 0 else ""
                doc.tablas.append(t)
        except Exception as e:                       # una tabla rara no debe tumbar el documento
            doc.errores.append(f"tablas: {e}")
        try:
            for f, n in _figuras(ruta, paginas):
                pos = texto.find(f"Figura {f.numero}.")
                f.seccion = _seccion_en(secs, pos) if pos >= 0 else ""
                doc.figuras.append(f)
        except Exception as e:
            doc.errores.append(f"figuras: {e}")
        ids = [r.id for r in doc.requisitos]
        for t in doc.tablas:
            ids += [f[0].split(" ")[0] for f in t.filas if f and RE_ID_FILA.match(f[0].split(" ")[0])]
        doc.ids_definidos = ids
    CACHE.mkdir(exist_ok=True)
    cache.write_text(json.dumps(doc.dict(), ensure_ascii=False), encoding="utf-8")
    return doc


def _desde_json(d: dict) -> Documento:
    doc = Documento(**{k: v for k, v in d.items() if k not in ("secciones", "requisitos", "tablas", "figuras")})
    doc.secciones = [Seccion(**s) for s in d["secciones"]]
    doc.requisitos = [Requisito(**r) for r in d["requisitos"]]
    doc.tablas = [Tabla(**t) for t in d["tablas"]]
    doc.figuras = [Figura(**{**f, "bbox": tuple(f["bbox"])}) for f in d["figuras"]]
    return doc


def resumen(doc: Documento) -> str:
    return (f"{doc.codigo} v{doc.version} · {doc.paginas} pág · {'ESCANEADO · ' if doc.escaneado else ''}"
            f"{len(doc.secciones)} secciones · {len(doc.requisitos)} requisitos · {len(doc.tablas)} tablas "
            f"({sum(len(t.filas) for t in doc.tablas)} filas) · {len(doc.figuras)} figuras"
            + (f" · errores: {doc.errores}" if doc.errores else ""))


if __name__ == "__main__":
    import sys
    d = ingerir(Path(sys.argv[1]))
    print(resumen(d))
    print(json.dumps(asdict(d), ensure_ascii=False, indent=1)[:4000])
