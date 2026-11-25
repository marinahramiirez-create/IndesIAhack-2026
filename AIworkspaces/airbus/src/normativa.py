"""
Normativa EASA → lista de cláusulas con su ID (trazabilidad hallazgo → regla).

Fuente: "Easy Access Rules for Information Security" de EASA (Part-IS, Reg. UE 2022/1645 y 2023/203),
formato XML "legible por máquina" (es un Word guardado como XML plano).
Descarga pública: https://www.easa.europa.eu/en/document-library/easy-access-rules/
                  easy-access-rules-information-security-regulations-eu-2023203-and-20221645

Cómo está hecho el XML:
  - En /customXml hay una etiqueta <er:topic sdt-id=... source-title="IS.I.OR.205 ..." TypeOfContent="IR ...">
    por cada cláusula (metadatos).
  - En /word/document.xml cada cláusula es un bloque <w:sdt> con <w:tag w:val="topic"/> y <w:id w:val=sdt-id/>,
    con sus párrafos dentro.  →  unimos los dos por sdt-id.

Uso:
    python -m src.normativa ruta/al/archivo.xml     # genera normativa/clausulas.json
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import config

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PKG = "{http://schemas.microsoft.com/office/2006/xmlPackage}"

# Tipos de contenido EASA: IR = regla obligatoria; AMC = medio aceptable de cumplimiento; GM = guía
TIPOS = {"IR": "IR", "AMC": "AMC", "GM": "GM"}


def _texto_parrafo(p) -> str:
    trozos = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            trozos.append(el.text)
        elif el.tag == W + "tab":
            trozos.append(" ")
    return re.sub(r"\s+", " ", "".join(trozos)).strip()


def _estilo(p) -> str:
    ps = p.find(f"{W}pPr/{W}pStyle")
    return ps.get(W + "val", "") if ps is not None else ""


def _metadatos(raiz) -> dict[str, dict]:
    """sdt-id → metadatos de <er:topic>."""
    meta = {}
    for el in raiz.iter():
        if el.tag.endswith("}topic") and el.get("sdt-id"):
            meta[el.get("sdt-id")] = {
                "source_title": el.get("source-title", ""),
                "tipo": (el.get("TypeOfContent", "") or "").split(" ")[0].strip(";"),
                "fuente": el.get("RegulatorySource", ""),
                "erules_id": el.get("ERulesId", ""),
            }
    return meta


def _apartados(parrafos: list[str]) -> list[dict]:
    """Agrupa los párrafos por apartado de primer nivel: (a), (b)... para poder citar 'IS.I.OR.245(b)'."""
    salida, actual = [], None
    for t in parrafos:
        m = re.match(r"^\(([a-z])\)\s*(.*)", t)
        if m:
            actual = {"apartado": m.group(1), "texto": m.group(2)}
            salida.append(actual)
        elif actual is not None:
            actual["texto"] += "\n" + t
    return salida


def parsear_xml(ruta: Path) -> list[dict]:
    raiz = ET.parse(ruta).getroot()
    meta = _metadatos(raiz)
    documento = None
    for parte in raiz.iter(PKG + "part"):
        if parte.get(PKG + "name") == "/word/document.xml":
            documento = parte
            break
    if documento is None:
        raise ValueError("No encuentro /word/document.xml dentro del XML de EASA")

    clausulas = []
    for sdt in documento.iter(W + "sdt"):
        tag = sdt.find(f"{W}sdtPr/{W}tag")
        sid = sdt.find(f"{W}sdtPr/{W}id")
        if tag is None or tag.get(W + "val") != "topic" or sid is None:
            continue
        m = meta.get(sid.get(W + "val"))
        if not m:
            continue
        contenido = sdt.find(W + "sdtContent")
        parrafos = []
        for p in contenido.iter(W + "p"):
            if _estilo(p) == "Dxshortdesc":   # línea "Regulation (EU) 2023/203" (ya está en metadatos)
                continue
            t = _texto_parrafo(p)
            if t:
                parrafos.append(t)
        if not parrafos:
            continue
        titulo_completo = parrafos[0]
        # ID de la cláusula: "IS.I.OR.205", "AMC1 IS.I.OR.205(a)", "GM2 IS.I.OR.200"...
        mid = re.match(r"^((?:AMC|GM)\d*\s+)?([A-Z]{2,}\.[A-Z]+(?:\.[A-Z]+)*\.\d+[A-Za-z0-9()]*|Article \d+)", titulo_completo)
        cid = (mid.group(0).strip() if mid else m["source_title"].split(" ")[0])
        if not cid:
            continue
        if cid.startswith("Article"):   # "Article 1" existe en los dos reglamentos → se añade cuál
            cid = f"{cid} ({m['fuente'].replace('Regulation (EU) ', '').strip(';')})"
        clausulas.append({
            "id": cid,
            "titulo": titulo_completo[len(cid):].strip() or m["source_title"],
            "tipo": TIPOS.get(m["tipo"], "otro"),
            "fuente": m["fuente"],
            "texto": "\n".join(parrafos[1:]),
            "apartados": _apartados(parrafos[1:]),
        })
    return clausulas


def cargar(solo_ir: bool = False) -> list[dict]:
    """Cláusulas ya extraídas (normativa/clausulas.json)."""
    ruta = config.RUTA_CLAUSULAS
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta}. Ejecuta: python -m src.normativa ruta/al/EAR_Information_Security.xml")
    clausulas = json.loads(ruta.read_text(encoding="utf-8"))
    if solo_ir:
        clausulas = [c for c in clausulas if c["tipo"] == "IR"]
    return clausulas


def por_id() -> dict[str, dict]:
    return {c["id"]: c for c in cargar()}


def url_clausula(cid: str) -> str:
    """Enlace para el informe. EASA no tiene URL por cláusula: se enlaza la versión online buscando el ID."""
    return ("https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/"
            f"easy-access-rules-information-security-0#:~:text={cid.replace(' ', '%20')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cl = parsear_xml(Path(sys.argv[1]))
    config.RUTA_CLAUSULAS.parent.mkdir(exist_ok=True)
    config.RUTA_CLAUSULAS.write_text(json.dumps(cl, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"{len(cl)} cláusulas → {config.RUTA_CLAUSULAS}")
    print("por tipo:", dict(Counter(c["tipo"] for c in cl)))
    print("ejemplos IR:", [c["id"] for c in cl if c["tipo"] == "IR"][:15])
