"""
Detectores de prosa (requisitos redactados).

  recomendacion   un requisito de seguridad formulado como recomendación («se recomienda», «debería»):
                  los propios documentos declaran que eso NO es vinculante → la medida no es obligatoria.
  no_verificable  requisito sin método de verificación («Verif.: —») o con una fórmula vaga sin criterio
                  medible («con la debida diligencia», «de la mejor manera posible»).
"""
import re

from nimbus.detectores.comun import clausula_valida, hallazgo, requisitos_de, ubic_req

RE_RECOMENDACION = re.compile(r"\bse recomienda\b|\bdeber[ií]a(?:n)?\b|\bse aconseja\b|\bopcional(?:mente)?\b", re.I)
VAGAS = ["debida diligencia", "mejor manera posible", "en la medida de lo posible", "siempre que sea posible",
         "cuando sea posible", "razonablemente", "de forma razonable", "resiliente", "según se estime",
         "cuando se considere oportuno", "suficientemente seguro", "lo más seguro posible"]
SIN_VERIF = {"—", "-", "–", "n/a", "na", ""}


def recomendacion(doc, k):
    salida = []
    for r in requisitos_de(doc):
        m = RE_RECOMENDACION.search(r.texto)
        if m:
            salida.append(hallazgo(
                doc, ubic_req(r), "No cumple", clausula_valida(r.clausula),
                f"Formulado como recomendación («{m.group(0)}»), no como obligación: la medida queda a criterio "
                f"de quien la aplica.", "prosa.recomendacion", evidencia=r.texto[:240], confianza=0.75, pagina=r.pagina))
    return salida


def no_verificable(doc, k):
    salida = []
    for r in requisitos_de(doc):
        texto = r.texto.lower()
        vaga = next((v for v in VAGAS if v in texto), None)
        sin_metodo = r.verificacion.strip().strip(".").lower() in SIN_VERIF and r.verificacion != ""
        if (vaga and not re.search(r"\d", texto)) or sin_metodo:
            motivo = f"«{vaga}» no fija un criterio medible" if vaga else "no tiene método de verificación («Verif.: —»)"
            salida.append(hallazgo(doc, ubic_req(r), "No verificable", clausula_valida(r.clausula),
                                   f"Requisito no verificable: {motivo}.", "prosa.no_verificable",
                                   evidencia=r.texto[:240], confianza=0.8 if (vaga and sin_metodo) else 0.65,
                                   pagina=r.pagina))
    return salida
