"""
Prueba de la integración del LLM SIN claves, con un LLM simulado que responde lo que le indicamos.
No mide la calidad del LLM (eso solo se puede con Azure); comprueba que las salvaguardas funcionan:

  1. Si el LLM elige otra obligación de las candidatas → se usa (reordenación).
  2. Si el LLM devuelve un ID que no está entre las candidatas → se ignora (no inventa cláusulas).
  3. Si dice "presente" pero su cita no está literalmente en el requisito → no cuenta (verificador de citas).
  4. Si los juicios no coinciden → "Revisar".
  5. Los límites numéricos los decide el código aunque el LLM diga que todo está bien.

Ejecutar desde airbus/:   python -m tests.test_llm_simulado
"""
import json
from types import SimpleNamespace

from src import auditor, llm, rag


class LLMSimulado:
    """Imita client.chat.completions.create devolviendo respuestas guionizadas en orden."""

    def __init__(self, respuestas: list[dict]):
        self.respuestas = list(respuestas)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        r = self.respuestas.pop(0) if self.respuestas else {"elementos": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(r)))])


def usar(respuestas):
    llm.CLIENTE_FALSO = (LLMSimulado(respuestas), "simulado")


def elementos(ob_id, presentes: dict):
    ob = next(o for o in rag.obligaciones() if o["id"] == ob_id)
    return {"elementos": [{"nombre": e["nombre"], "presente": e["nombre"] in presentes,
                           "cita_requisito": presentes.get(e["nombre"], "")} for e in ob["elementos"]]}


def caso(nombre, req_texto, respuestas, comprobar):
    usar(respuestas)
    h = auditor.auditar({"req_id": "T-1", "texto": req_texto})
    ok = bool(comprobar(h))
    print(f"{'OK ' if ok else 'MAL'} {nombre}: {h['veredicto']} · {h['obligacion_id']} · {h['justificacion'][:110]}")
    return ok


def main():
    resultados = []
    # 1. reordenación: "audit trails" → el RAG trae otra cosa primero; el LLM elige OB-245-a
    req = "Audit trails of the maintenance IT systems shall be retained for seven years."
    cands = rag.buscar_obligaciones(auditor.expandir(req), k=6)   # misma consulta que usa el auditor
    assert any(c["id"] == "OB-245-a" for c in cands), "OB-245-a debería estar entre las 6 candidatas"
    presente = {"periodo de retención": "retained for seven years"}
    resultados.append(caso("1 reordenación", req,
                           [{"obligacion_id": "OB-245-a", "motivo": "audit trails son registros"}] + [elementos("OB-245-a", presente)] * 3,
                           lambda h: h["obligacion_id"] == "OB-245-a" and h["veredicto"] == "Cumple"))
    # 2. ID inventado → se ignora y se usa la primera candidata del RAG
    resultados.append(caso("2 ID inventado ignorado", req,
                           [{"obligacion_id": "OB-999-z", "motivo": "inventado"}] + [elementos(cands[0]["id"], {})] * 3,
                           lambda h: h["obligacion_id"] == cands[0]["id"]))
    # 3. cita falsa: dice que está "every six months" pero el requisito no lo dice → no cuenta → No cumple
    req3 = "The ISMS performance shall be measured with KPIs."
    falsa = {"indicadores de rendimiento": "KPIs", "calendario predefinido o tras incidente": "every six months"}
    resultados.append(caso("3 cita falsa rechazada", req3,
                           [{"obligacion_id": "OB-260-a", "motivo": ""}] + [elementos("OB-260-a", falsa)] * 3,
                           lambda h: h["veredicto"] == "No cumple" and "calendario" in " ".join(h["faltan"])))
    # 4. juicios que no coinciden → Revisar
    req4 = "The ISMS performance shall be measured with KPIs every six months."
    si = {"indicadores de rendimiento": "KPIs", "calendario predefinido o tras incidente": "every six months"}
    no = {"indicadores de rendimiento": "KPIs"}
    resultados.append(caso("4 discrepancia → Revisar", req4,
                           [{"obligacion_id": "OB-260-a", "motivo": ""}, elementos("OB-260-a", si),
                            elementos("OB-260-a", no), elementos("OB-260-a", si)],
                           lambda h: h["veredicto"] == "Revisar"))
    # 5. el LLM ve todo presente, pero 5 días > 72 h → el código manda: No cumple
    req5 = "Incidents shall be reported to the competent authority within 5 days."
    resultados.append(caso("5 límite numérico por código", req5,
                           [{"obligacion_id": "OB-230-c", "motivo": ""}] +
                           [elementos("OB-230-c", {"notificar a la autoridad competente": "competent authority"})] * 3,
                           lambda h: h["veredicto"] == "No cumple" and h["violaciones"]))
    llm.CLIENTE_FALSO = None
    print(f"\n{sum(resultados)}/{len(resultados)} comprobaciones superadas")


if __name__ == "__main__":
    main()
