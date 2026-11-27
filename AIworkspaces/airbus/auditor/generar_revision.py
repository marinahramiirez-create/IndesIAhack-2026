"""
Genera la pantalla de revisión con el diseño de Valentina y los datos reales del auditor.

    .venv\\Scripts\\python generar_revision.py [--csv salidas\\respuestas.csv] [--no-abrir]

Entrada: respuestas.csv + su traza (lo que produce auditar.py) y los PDF del corpus.
Salida:  salidas\\revision\\index.html + salidas\\revision\\paginas\\*.jpg (una imagen por página).
La página funciona sola, sin servidor: doble clic en index.html. Las decisiones del revisor se guardan en el
navegador y se exportan con el botón «Exportar feedback.csv»; nunca modifican respuestas.csv.
Las imágenes ya generadas se reutilizan: volver a ejecutarlo tras una auditoría nueva tarda segundos.
"""
import argparse
import hashlib
import json
import re
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymupdf

from src import ingesta

RAIZ = Path(__file__).resolve().parent
from src.rutas import CORPUS  # noqa: E402  (ruta del corpus: .env o carpetas habituales)
EASA_URL = "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-information-security-part"
PATRON_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]{1,8}){0,3}-\d{2,4}\b|\b[A-Z]-\d{2,4}\b|\bu\d{3,5}\b")
ZOOM = 1.4
VERSION_TEXTO = "2"        # formato del texto de cada página (2 = párrafos y tablas, src/texto_paginas.py)


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[|«»\"“”]", " ", str(t).lower())).strip()


def fragmentos(evidencia: str) -> list[str]:
    """La cita se busca entera y, si no aparece así (saltos de línea, celdas de tabla), por trozos de 6 palabras."""
    partes = [p.strip(" .«»\"“”") for p in re.split(r"\s*\|\s*|\n", evidencia) if len(p.strip()) >= 6]
    out = []
    for p in partes:
        w = p.split()
        out += [p] if len(w) <= 8 else [" ".join(w[i:i + 6]) for i in range(0, len(w), 6) if len(w[i:i + 6]) >= 3]
    return out


def pagina_hallazgo(r: dict, doc) -> int:
    ev = norm(r["evidencia"])[:60]
    if ev:
        for i, p in enumerate(doc.paginas, 1):
            if ev in norm(p):
                return i
    unidades = {u.id: u.pagina for u in doc.unidades}
    for i in PATRON_ID.findall(r["ubicacion"]):
        if i in unidades:
            return unidades[i]
    m = re.search(r"(Tabla|Figura) (\d+)", r["ubicacion"])
    if m:
        for t in (doc.tablas if m.group(1) == "Tabla" else doc.figuras):
            if str(t.get("n")) == m.group(2):
                return t["pagina"]
    return 1


def cajas(pag, evidencia: str, ubicacion: str) -> list[dict]:
    """Posiciones (0-1) de la cita y del identificador en la página, como las cajas del prototipo."""
    W, H = pag.rect.width, pag.rect.height
    # Anclas: identificadores de la cita o de la ubicación presentes en la página (p. ej. la fila VUL-2026-022)
    anclas = []
    for i in dict.fromkeys(PATRON_ID.findall(evidencia) + PATRON_ID.findall(ubicacion)):
        anclas += pag.search_for(i)[:1]
    fila = "|" in evidencia and anclas            # cita de una fila de tabla: solo lo que está en esa línea

    def en_fila(r):
        return any(abs((r.y0 + r.y1) / 2 - (a.y0 + a.y1) / 2) < max(a.height, 4) for a in anclas)

    rects = list(anclas)
    for f in fragmentos(evidencia):
        hits = pag.search_for(f)
        if fila:
            hits = [r for r in hits if en_fila(r)]
        elif len(hits) > 1 and len(f) < 20:     # trozo corto repetido en la página: ambiguo, no se marca
            hits = []
        rects += hits
    return [{"p": pag.number + 1, "x": round(r.x0 / W, 4), "y": round(r.y0 / H, 4),
             "w": round(r.width / W, 4), "h": round(r.height / H, 4)} for r in rects[:12]]


def familia(nombre: str) -> str:
    return re.sub(r"^\d+_", "", nombre).replace("_", " ").capitalize()


def metricas(salidas: Path) -> dict | None:
    p = salidas / "metricas_sin_nucleo.txt"
    if not p.exists():
        return None
    t = p.read_text(encoding="utf-8")
    g = lambda pat: re.search(pat, t)
    a = g(r"aciertos: (\d+) \| defectos en la clave: (\d+)")
    c = g(r"cláusula correcta en aciertos: (\d+)/(\d+)")
    fam = g(r"Recall por familia: (.+)")
    return {"alcance": "Documentos con clave del kit de desarrollo, sin los 5 del núcleo, como en la evaluación final.",
            "f1": g(r"F1 ([\d.]+)").group(1).replace(".", ","),
            "precision": g(r"Precisión ([\d.]+)").group(1).replace(".", ","),
            "recall": g(r"Recall ([\d.]+)").group(1).replace(".", ","),
            "clausula": f"{int(c.group(1)) / int(c.group(2)) * 100:.0f} %" if c else "—",
            "encontrados": f"{a.group(1)}/{a.group(2)}" if a else "—",
            "familias": [{"n": familia(n), "ok": int(o), "total": int(tt)}
                         for n, o, tt in re.findall(r"(\S+) (\d+)/(\d+)", fam.group(1))] if fam else []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(RAIZ / "salidas" / "respuestas.csv"))
    ap.add_argument("--no-abrir", action="store_true")
    a = ap.parse_args()
    ruta_csv = Path(a.csv)
    if not ruta_csv.exists():
        raise SystemExit(f"\nTodavía no hay resultados ({ruta_csv}).\n"
                         "  → Ejecuta primero el auditor y espera a que termine:\n"
                         "      .\\.venv\\Scripts\\python auditar.py\n"
                         "  → Después vuelve a ejecutar: .\\.venv\\Scripts\\python generar_revision.py\n")
    from src.rutas import ayuda_corpus, buscar_corpus
    from src.estructura import pagina_html
    corpus = buscar_corpus()
    if not corpus:
        raise SystemExit(ayuda_corpus())
    destino = RAIZ / "salidas" / "revision"
    (destino / "paginas").mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(ruta_csv, dtype=str).fillna("")
    traza_f = ruta_csv.with_name(ruta_csv.stem + "_traza.jsonl")
    traza = [json.loads(l) for l in open(traza_f, encoding="utf-8")] if traza_f.exists() else []
    fuente = {(t["documento"], t["ubicacion"]): t.get("fuente", "") for t in traza if t.get("aceptado")}

    print("Leyendo el corpus (usa la caché de transcripciones, sin coste de IA)…")
    docs = {}
    for f in sorted(corpus.rglob("*.pdf")):
        try:
            d = ingesta.leer(f, vision=True)
        except Exception:
            try:                                    # sin claves o sin caché: se lee sin visión (el escaneado
                d = ingesta.leer(f, vision=False)   # sale sin texto, pero su página e hallazgos se ven igual)
            except Exception as e:
                print("  aviso:", f.name, repr(e))
                continue
        if d.codigo:
            docs[d.codigo] = (d, f)

    from src.texto_paginas import texto_legible
    marca_txt = destino / "paginas" / "_texto_version.txt"      # si cambia el formato del texto, se regenera
    texto_al_dia = marca_txt.exists() and marca_txt.read_text().strip() == VERSION_TEXTO
    if not texto_al_dia:
        print("Preparando el texto legible de cada página (solo la primera vez, ≈1 min)…")
    info_docs, res = {}, []
    for cod, (d, f) in docs.items():
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", cod)
        pdf = pymupdf.open(f)
        for n, pag in enumerate(pdf, 1):          # imagen de cada página (se reutiliza si ya existe)
            img = destino / "paginas" / f"{slug}_{n}.jpg"
            if not img.exists():
                img.write_bytes(pag.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).tobytes("jpg", jpg_quality=72))
            # Texto legible de la página (párrafos y tablas, src/texto_paginas.py): es el punto de partida de las
            # versiones editables. Escaneado sin texto digital → la transcripción con visión, si hay caché.
            # Se reutiliza si ya existe en el formato actual. El PDF original nunca se modifica.
            txt_f = destino / "paginas" / f"{slug}_{n}.txt"
            if not (txt_f.exists() and texto_al_dia):
                txt = texto_legible(pag) or (d.paginas[n - 1] if n - 1 < len(d.paginas) else "")
                txt_f.write_text(txt or "", encoding="utf-8")
            # Estructura (títulos, párrafos y tablas) para el editor; se reutiliza si ya existe (find_tables es lento)
            estr = destino / "paginas" / f"{slug}_{n}.html"
            if not estr.exists():
                html = pagina_html(pag)
                if html:
                    estr.write_text(html, encoding="utf-8")
        info_docs[cod] = {"slug": slug, "titulo": re.sub(r"\s*Documento$", "", d.titulo.strip()), "version": d.version, "familia": familia(f.parent.name),
                          "paginas": pdf.page_count, "escaneado": d.escaneado}
        for r in df[df.documento == cod].to_dict("records"):
            n = pagina_hallazgo(r, d)
            res.append({"documento": cod, "ubicacion": r["ubicacion"], "tipo": r["tipo"], "clausula": r["clausula"],
                        "justificacion": r["justificacion"], "leido": r["evidencia"], "pagina": n,
                        "base": fuente.get((cod, r["ubicacion"]), ""), "origen": r.get("origen", ""),
                        "conf": float(r.get("confianza") or 0),
                        "boxes": [] if d.escaneado else cajas(pdf[n - 1], r["evidencia"], r["ubicacion"])})
    marca_txt.write_text(VERSION_TEXTO)
    sin_pdf = sorted(set(df.documento) - set(docs))
    if sin_pdf:
        print("  aviso: hallazgos de documentos sin PDF en el corpus:", sin_pdf)

    # Cifras reales de cada agente (de la traza de la última ejecución)
    t = pd.DataFrame(traza)
    acept = int(t.aceptado.sum()) if len(t) else 0
    desc = len(t) - acept
    orig = (t.origen.astype(str).str.replace(r"^R\d+$", "reglas", regex=True).value_counts() if len(t) else pd.Series(dtype=int))
    motivos = (t[~t.aceptado].descarte.str.extract(r"^(V\d)")[0].value_counts() if desc else pd.Series(dtype=int))
    paginas = sum(i["paginas"] for i in info_docs.values())
    etapas = [
        {"n": "Lectura del PDF", "d": "Convierte cada documento en texto, tablas y figuras. Los escaneados se transcriben con visión.",
         "met": [["Documentos", str(len(docs))], ["Páginas", str(paginas)],
                 ["Escaneados", str(sum(d.escaneado for d, _ in docs.values()))],
                 ["Figuras", str(sum(len(d.figuras) for d, _ in docs.values()))]],
         "act": ["Extraer el texto de cada página", "Detectar código y versión en la portada",
                 "Localizar requisitos, filas de registro y riesgos por su identificador",
                 "Transcribir con visión los PDF escaneados"]},
        {"n": "Índice normativo", "d": "Part-IS (IS.I.OR.200 a 260), STD-SEC-001 vigente y LISTA-DOC, cargados una sola vez.",
         "met": [["Cláusulas Part-IS", "13"], ["Referencias", "STD-SEC-001 + LISTA-DOC"]],
         "act": ["Cargar el texto oficial de Part-IS", "Elegir la versión vigente de STD-SEC-001 según LISTA-DOC",
                 "Relacionar cada documento con los que cita"]},
        {"n": "Agente de documentos", "d": "Reglas deterministas + agente LLM sobre el texto + visión en las páginas con figuras.",
         "met": [["Propuestas", str(len(t))]] + [[k, str(v)] for k, v in orig.items()],
         "act": ["Comparar cada requisito o fila con la norma y el estándar", "Copiar la cita literal que lo demuestra",
                 "Dar las fechas de los plazos: la cuenta la hace el código", "Comparar los diagramas con el texto"]},
        {"n": "Verificación de citas", "d": "Código, no IA: formato, ubicación existente, cita literal, plazo recalculado y confianza.",
         "met": [["Aceptadas", str(acept)], ["Descartadas", str(desc)]] + [[k, str(v)] for k, v in motivos.items()],
         "act": ["V1 formato oficial de tipo y cláusula", "V2 la ubicación existe en el documento",
                 "V3 la cita aparece literalmente", "V4 el plazo calculado incumple de verdad", "V5 umbral de confianza"]},
        {"n": "Generación de respuestas.csv", "d": "Quita duplicados y escribe las filas en el formato del reto, sin intervención manual.",
         "met": [["Filas", str(len(df))], ["Documentos", str(df.documento.nunique())],
                 ["Con cláusula", f"{(df.clausula != '—').mean() * 100:.0f} %"]],
         "act": ["Quitar duplicados (mismo documento y mismo identificador)", "Ordenar por documento y ubicación",
                 "Escribir respuestas.csv y la traza"]},
    ]
    log = [f"{x['documento']} · {x['ubicacion']} · {x['origen']} → {x['descarte']}" for x in traza if not x.get("aceptado")]

    datos = {"id": hashlib.md5(ruta_csv.read_bytes()).hexdigest()[:8], "fichero": ruta_csv.name, "easa": EASA_URL,
             "carpeta": "paginas", "docs": info_docs, "res": res, "etapas": etapas, "metricas": metricas(RAIZ / "salidas"),
             # Antigüedad de los documentos del corpus en Inicio: cuenta desde que se ejecutó la auditoría
             "fecha_auditoria": datetime.fromtimestamp(ruta_csv.stat().st_mtime).isoformat(timespec="seconds"),
             "log": log}
    plantilla = (RAIZ / "src" / "plantilla_revision.html").read_text(encoding="utf-8")
    js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    salida = destino / "index.html"
    salida.write_text(plantilla.replace("/*__DATOS__*/null", js), encoding="utf-8")
    print(f"{len(res)} hallazgos · {len(info_docs)} documentos · {paginas} páginas → {salida}")
    if not a.no_abrir:
        webbrowser.open(salida.as_uri())


if __name__ == "__main__":
    main()
