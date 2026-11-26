"""
Conocimiento de referencia (se carga UNA vez por ejecución y se reutiliza en todos los documentos):
  1. Part-IS (IS.I.OR.200-260, texto del reglamento) → plazos legales que no están en los documentos internos.
  2. STD-SEC-001 VIGENTE → valores corporativos. Si hay varias versiones, se usa la vigente (nunca la sustituida).
  3. LISTA-DOC → qué documentos y versiones están en vigor.
Y, para cada documento, los documentos del corpus que cita (cruces entre documentos / registros).
"""
import json
import re
from pathlib import Path

from src.ingesta import Documento

RAIZ = Path(__file__).resolve().parent.parent
CODIGOS_REFERENCIA = ("STD-SEC-001", "LISTA-DOC")
MAX_RELACIONADO = 40000      # caracteres por documento relacionado
MAX_RELACIONADOS = 3


def part_is() -> str:
    ir = json.loads((RAIZ / "normativa" / "part_is_ir.json").read_text(encoding="utf-8"))
    return "\n\n".join(f"### {c['id']} — {c['titulo']}\n{c['texto']}" for c in ir)


def _num_version(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return -1


def estandar_vigente(docs: list[Documento]) -> Documento | None:
    """La versión vigente del estándar: la que su portada declara «vigente»; si no, la de mayor versión."""
    std = [d for d in docs if d.codigo.startswith("STD-SEC-001")]
    vig = [d for d in std if re.search(r"\(vigente\)", d.paginas[0] if d.paginas else "", re.I)]
    cand = vig or std
    return max(cand, key=lambda d: _num_version(d.version)) if cand else None


def bloque(docs: list[Documento]) -> str:
    std = estandar_vigente(docs)
    lista = next((d for d in docs if d.codigo == "LISTA-DOC"), None)
    partes = ["## PART-IS (Reglamento (UE) 2023/203, Anexo II, IS.I.OR) — rango 1\n" + part_is()]
    if std:
        partes.append(f"## {std.codigo} v{std.version} (VIGENTE) — estándar corporativo, rango 2, sin defectos\n"
                      + std.texto)
    if lista:
        partes.append(f"## {lista.codigo} v{lista.version} — lista maestra, rango 3\n" + lista.texto)
    return "\n\n".join(partes)


PATRON_IDS = re.compile(r"\b[A-Z][A-Z0-9]{0,6}(?:-[A-Z0-9]{1,8}){0,3}-\d{2,4}\b|\bu\d{3,5}\b")


def _ids(doc: Documento) -> set[str]:
    if not hasattr(doc, "_ids_cache"):
        doc._ids_cache = set(PATRON_IDS.findall(re.sub(r"-\s+(?=[A-Z0-9])", "-", doc.texto)))
    return doc._ids_cache


def relacionados(doc: Documento, docs: list[Documento]) -> list[Documento]:
    """Documentos con los que hay que cruzar este (canal «cruzado» de la guía). Dos señales genéricas:
      - lo cita por su código (un informe de verificación cita la especificación que verifica);
      - comparten muchos identificadores de fila (registro de cuentas y registro de personal comparten los
        E-xxxx; vulnerabilidades y cambios comparten los RFC-...), aunque no se citen por el código."""
    texto = doc.texto
    mios = _ids(doc)
    puntos = []
    for d in docs:
        if d is doc or not d.codigo or d.codigo.startswith(CODIGOS_REFERENCIA) or d.codigo == doc.codigo:
            continue
        citas = len(re.findall(r"(?<![A-Z0-9-])" + re.escape(d.codigo) + r"(?![A-Z0-9-])", texto))
        # solo IDs distintivos: con 3+ cifras (E-1087, KEY-014, RFC-2026-089). R-31, P-07, MSG-07 se repiten en
        # todos los documentos de una familia con otro significado y no indican relación
        comunes = len({i for i in mios & _ids(d) if re.search(r"\d{3,}$", i)} - {d.codigo, doc.codigo})
        p = 1000 * min(citas, 5) + (comunes if comunes >= 5 else 0)   # citarlo explícitamente manda
        if p:
            puntos.append((p, d))
    puntos.sort(key=lambda x: -x[0])
    return [d for _, d in puntos[:MAX_RELACIONADOS]]
