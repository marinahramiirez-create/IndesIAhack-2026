"""
Comprobaciones deterministas (sin LLM). Solo reglas GENÉRICAS que valen para cualquier documento del corpus,
nunca reglas hechas para un documento concreto (guía §6.1). Cada hallazgo lleva la evidencia literal.

  R1 Referencia rota: un requisito cita un ID con el mismo prefijo que los del documento y ese ID no existe.
  R2 ID duplicado: el mismo identificador se define dos veces.
  R3 Obligación formulada como recomendación ("se recomienda", "debería") en un requisito de seguridad.
  R4 Requisito no verificable: método de verificación vacío ("Verif.: —") y redacción sin criterio medible.
"""
import re
from collections import Counter

from src.ingesta import PATRON_ID, Documento
from src.modelo import Hallazgo

RECOMENDACION = re.compile(r"\bse recomienda\b|\bdebería\b|\bes aconsejable\b|\bpreferiblemente\b", re.I)
VAGO = re.compile(r"resiliente|adecuad[oa]s?|debida diligencia|razonable|en la medida de lo posible|"
                  r"cuando sea posible|apropiad[oa]s?|suficiente|robust[oa]", re.I)
SIN_VERIF = re.compile(r"Verif\.?\s*:\s*(—|-|N/?A|ninguna)\s*\.?\s*$", re.I)


def _prefijo(id_: str) -> str:
    return id_.rsplit("-", 1)[0]


def _frase(texto: str) -> str:
    """El enunciado del requisito, sin la coletilla 'Tipo: ... Verif.: ...'."""
    return re.split(r"\s+Tipo:\s", texto)[0].strip()


def revisar(doc: Documento) -> list[Hallazgo]:
    salida: list[Hallazgo] = []
    if not doc.unidades:
        return salida
    ids = doc.ids()
    prefijos = Counter(_prefijo(u.id) for u in doc.unidades)
    prefijo_req = prefijos.most_common(1)[0][0]

    # R2 duplicados
    for id_, n in Counter(u.id for u in doc.unidades).items():
        if n > 1:
            u = next(x for x in doc.unidades if x.id == id_)
            salida.append(Hallazgo(doc.codigo, id_, "Trazabilidad incorrecta", u.clausula or "—",
                                   f"El identificador {id_} aparece definido {n} veces.", evidencia=id_,
                                   origen="regla R2", confianza=0.9))

    for u in doc.unidades:
        frase = _frase(u.texto)
        # R1 referencia rota (solo IDs del mismo tipo que los requisitos del documento)
        for ref in set(PATRON_ID.findall(u.texto)) - {u.id}:
            if _prefijo(ref) == prefijo_req and ref not in ids:
                salida.append(Hallazgo(doc.codigo, u.id, "Trazabilidad incorrecta", "—",
                                       f"Referencia cruzada rota a {ref}, que no existe en el documento.",
                                       evidencia=ref, origen="regla R1", confianza=0.9))
        if _prefijo(u.id) != prefijo_req:
            continue    # R3/R4 solo para los requisitos, no para filas de otras tablas
        # R3 recomendación en vez de obligación
        m = RECOMENDACION.search(frase)
        if m:
            salida.append(Hallazgo(doc.codigo, u.id, "No cumple", u.clausula or "—",
                                   f"Control formulado como recomendación («{m.group(0)}»), no como obligación.",
                                   evidencia=m.group(0), origen="regla R3", confianza=0.75))
        # R4 sin verificación y con redacción vaga
        m_v = VAGO.search(frase)
        if SIN_VERIF.search(u.texto) and m_v:
            salida.append(Hallazgo(doc.codigo, u.id, "No verificable", u.clausula or "—",
                                   f"«{frase[:90]}»: sin criterio medible ni método de verificación.",
                                   evidencia=m_v.group(0), origen="regla R4", confianza=0.8))
    return salida
