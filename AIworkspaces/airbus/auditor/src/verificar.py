"""
Verificación por CÓDIGO de cada propuesta del LLM (guía §10.3: "exigid cita literal y ubicación, y comprobad
automáticamente que la cita existe"; "lo que se puede calcular con código no debe hacerlo un LLM").

Una propuesta se descarta (con motivo, para la traza) si:
  V1 el tipo o la cláusula no tienen el formato oficial (la cláusula se normaliza: IS.I.OR.210(a) → IS.I.OR.210)
  V2 la ubicación no contiene ningún identificador que exista en el documento auditado (o en el relacionado)
  V3 la evidencia no aparece literalmente en el documento auditado
  V4 el plazo calculado con código CUMPLE el máximo (el LLM se equivocó al ver un defecto)
  V5 la confianza declarada está por debajo del umbral
"""
import re
import unicodedata
from datetime import datetime

from src.modelo import PATRON_CLAUSULA_OK, TIPOS, Hallazgo

UMBRAL_CONFIANZA = 0.4
ANCLA = re.compile(r"[A-Z][A-Z0-9]{0,6}(?:-[A-Z0-9]{1,8}){0,3}-\d{2,4}[A-Z]?|\b(?:u|adm)[\w-]*\d+\b|\badm-[a-z]+-\w+|"
                   r"\bTabla \d+|\bFigura \d+|§\s?\d+(?:\.\d+)*|«[^»]{3,60}»")
# anclas que no son un identificador literal del texto (apartado, tabla, figura, cita): se aceptan si la evidencia
# se ha encontrado en el documento
ANCLA_GENERICA = re.compile(r"^(?:§|Tabla |Figura |«)")


def _norm(t: str) -> str:
    """Normaliza para comparar citas: minúsculas, sin comillas ni separadores de tabla, IDs partidos unidos."""
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[«»\"'“”‘’|]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"-\s+(?=[a-z0-9])", "-", t).strip()     # "RSK-C2L-\n01" → "rsk-c2l-01"


def normalizar_clausula(c: str) -> str:
    c = c.strip()
    if c in ("—", "-", "–", "N/A", ""):
        return "—"
    m = re.search(r"IS\.I\.OR\.(2\d\d)", c)
    return f"IS.I.OR.{m.group(1)}" if m else c


def _fecha(s: str) -> datetime | None:
    s = s.strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(datetime(2000, 1, 1).strftime(f))], f)
        except ValueError:
            continue
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    return datetime.strptime(m.group(0), "%Y-%m-%d") if m else None


def dias(desde: str, hasta: str) -> float | None:
    a, b = _fecha(desde), _fecha(hasta)
    return None if not (a and b) else (b - a).total_seconds() / 86400


def verificar(h: Hallazgo, texto_doc: str, texto_relacionados: str = "") -> Hallazgo | None:
    h.clausula = normalizar_clausula(h.clausula)
    if h.tipo not in TIPOS or (h.clausula != "—" and not PATRON_CLAUSULA_OK.match(h.clausula)):
        h.descarte = "V1 formato"
        return None
    doc_n = _norm(texto_doc)
    todo_n = doc_n + " " + _norm(texto_relacionados)
    ev = _norm(h.evidencia)
    if ev and ev not in doc_n:
        # tolera elipsis o cortes: basta con que estén los fragmentos largos de la cita
        trozos = [t.strip() for t in re.split(r"\.\.\.|…", ev) if len(t.strip()) >= 15]
        if not trozos or not all(t in doc_n for t in trozos):
            h.descarte = "V3 evidencia no encontrada en el documento"
            return None
    anclas = ANCLA.findall(h.ubicacion)
    literal = [a for a in anclas if not ANCLA_GENERICA.match(a)]
    existe = any(_norm(a) in todo_n for a in literal) if literal else bool(anclas and ev)
    if not existe:
        h.descarte = f"V2 ubicación sin identificador existente ({h.ubicacion})"
        return None
    if h.calculo is not None:
        d = dias(h.calculo.desde, h.calculo.hasta)
        if d is not None:
            if d <= h.calculo.maximo_dias + 1e-6:
                h.descarte = f"V4 plazo cumplido ({d:.1f} días ≤ {h.calculo.maximo_dias})"
                return None
            h.justificacion += f" [calculado: {d:.0f} días; máximo {h.calculo.maximo_dias:g}]"
    if h.confianza < UMBRAL_CONFIANZA:
        h.descarte = f"V5 confianza {h.confianza:.2f}"
        return None
    return h
