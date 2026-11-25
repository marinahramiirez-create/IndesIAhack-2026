"""
Arquitectura agéntica con LangGraph (la que propone el enunciado de Airbus):

                       ┌──────────── SUPERVISOR ────────────┐
                       │ decide el siguiente paso según el  │
                       │ estado (qué falta por hacer)       │
                       └─┬──────┬───────┬────────┬───────┬──┘
                Extractor  Auditor  Reflexión  Trazabilidad  Crítico → (interrupt HITL) → Cierre

  - Extractor:     documento → requisitos (ID, texto, sección, ubicación)
  - Auditor:       RAG + juez(es) → veredicto + cláusula + justificación por requisito
  - Reflexión:     los hallazgos con confianza baja se re-evalúan reformulando la búsqueda (máx. MAX_REFLEXIONES)
  - Trazabilidad:  verifica que cada cláusula citada existe en la normativa y calcula la cobertura de reglas
  - Crítico:       contradicciones entre requisitos y homogeneidad del detalle
  - Cierre:        con hitl=True el grafo se PARA antes de cerrar (interrupt) hasta que un revisor apruebe

Cada nodo deja una línea en 'traza' → se enseña en la interfaz ("qué hizo cada agente").
"""
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

import config
from src import auditor, consistencia, documento, llm, normativa


class Estado(TypedDict, total=False):
    ruta_documento: str
    requisitos: list[dict]
    hallazgos: dict[str, dict]          # req_id → hallazgo
    reflexiones: dict[str, int]         # req_id → nº de re-evaluaciones
    trazabilidad_hecha: bool
    cobertura: list[dict]
    contradicciones: list[dict]
    homogeneidad: list[dict]
    consistencia_hecha: bool
    cerrado: bool
    traza: list[str]


def _log(estado: Estado, texto: str) -> list[str]:
    return estado.get("traza", []) + [texto]


# ---------------------------------------------------------------- nodos
def extractor(e: Estado) -> Estado:
    reqs = documento.extraer(e.get("ruta_documento") or None)
    return {"requisitos": reqs, "hallazgos": {}, "reflexiones": {},
            "traza": _log(e, f"Extractor: {len(reqs)} requisitos extraídos del documento")}


def auditor_nodo(e: Estado) -> Estado:
    hallazgos = dict(e.get("hallazgos", {}))
    pendientes = [r for r in e["requisitos"] if r["req_id"] not in hallazgos]
    for r in pendientes:
        hallazgos[r["req_id"]] = auditor.auditar(r)
    juez = "reglas + LLM (autoconsistencia)" if llm.disponible() else "reglas (sin LLM configurado)"
    return {"hallazgos": hallazgos, "traza": _log(e, f"Auditor: {len(pendientes)} requisitos juzgados · juez: {juez}")}


def _necesita_reflexion(e: Estado) -> list[str]:
    return [rid for rid, h in e.get("hallazgos", {}).items()
            if h["veredicto"] != "No aplica" and h["confianza"] < config.UMBRAL_CONFIANZA
            and e.get("reflexiones", {}).get(rid, 0) < config.MAX_REFLEXIONES]


def reflexion(e: Estado) -> Estado:
    hallazgos, reflex = dict(e["hallazgos"]), dict(e.get("reflexiones", {}))
    reqs = {r["req_id"]: r for r in e["requisitos"]}
    cambios = []
    for rid in _necesita_reflexion(e):
        reflex[rid] = reflex.get(rid, 0) + 1
        antes = hallazgos[rid]
        consulta = llm.reformular(reqs[rid]["texto"]) or auditor.reformular(reqs[rid]["texto"])
        nuevo = auditor.auditar(reqs[rid], consulta=consulta)
        nuevo["reflexion"] = (f"Confianza baja ({antes['confianza']}) con {antes['obligacion_id']}; "
                              f"se reformuló la búsqueda → {nuevo['obligacion_id']} ({nuevo['confianza']}).")
        # Si aun así la confianza sigue baja, decide el humano
        if nuevo["confianza"] < config.UMBRAL_CONFIANZA and nuevo["veredicto"] == "Cumple":
            nuevo["veredicto"] = "Revisar"
            nuevo["justificacion"] += " Confianza baja tras la reflexión → revisión humana."
        if nuevo["score_recuperacion"] >= antes["score_recuperacion"] or nuevo["confianza"] > antes["confianza"]:
            hallazgos[rid] = nuevo
        else:
            antes = {**antes, "reflexion": nuevo["reflexion"] + " Se mantiene el juicio inicial."}
            if antes["veredicto"] == "Cumple":
                antes["veredicto"] = "Revisar"
            hallazgos[rid] = antes
        cambios.append(f"{rid}: {antes['obligacion_id']}→{hallazgos[rid]['obligacion_id']}")
    return {"hallazgos": hallazgos, "reflexiones": reflex,
            "traza": _log(e, f"Reflexión: {len(cambios)} hallazgos re-evaluados ({'; '.join(cambios)})")}


def trazabilidad(e: Estado) -> Estado:
    ids = {c["id"] for c in normativa.cargar()}
    hallazgos = {}
    for rid, h in e["hallazgos"].items():
        h = dict(h)
        h["clausula_existe"] = (h["clausula"] in ids) if h["clausula"] else None
        if h["clausula"] and not h["clausula_existe"]:
            h["veredicto"], h["justificacion"] = "Revisar", h["justificacion"] + " Cláusula citada inexistente."
        hallazgos[rid] = h
    # Cobertura: ¿qué reglas obligatorias (IR) de Part-IS cubre el documento?
    citadas = {h["clausula"] for h in hallazgos.values() if h["clausula"]}
    cobertura = [{"clausula": c["id"], "titulo": c["titulo"],
                  "requisitos": ", ".join(sorted(r for r, h in hallazgos.items() if h["clausula"] == c["id"])),
                  "cubierta": c["id"] in citadas}
                 for c in normativa.cargar(solo_ir=True) if c["id"].startswith("IS.I.OR.2")]
    n = sum(c["cubierta"] for c in cobertura)
    return {"hallazgos": hallazgos, "cobertura": cobertura, "trazabilidad_hecha": True,
            "traza": _log(e, f"Trazabilidad: citas verificadas contra la normativa; cobertura {n}/{len(cobertura)} reglas IS.I.OR")}


def critico(e: Estado) -> Estado:
    contra = consistencia.contradicciones(e["requisitos"])
    homo = consistencia.homogeneidad(e["requisitos"])
    return {"contradicciones": contra, "homogeneidad": homo, "consistencia_hecha": True,
            "traza": _log(e, f"Crítico: {len(contra)} contradicciones y {len(homo)} requisitos con detalle insuficiente")}


def cierre(e: Estado) -> Estado:
    return {"cerrado": True, "traza": _log(e, "Cierre: informe listo")}


def supervisor(e: Estado) -> Estado:
    return {}


def siguiente(e: Estado) -> str:
    if not e.get("requisitos"):
        return "extractor"
    if len(e.get("hallazgos", {})) < len(e["requisitos"]):
        return "auditor"
    if _necesita_reflexion(e):
        return "reflexion"
    if not e.get("trazabilidad_hecha"):
        return "trazabilidad"
    if not e.get("consistencia_hecha"):
        return "critico"
    if not e.get("cerrado"):
        return "cierre"
    return END


# ---------------------------------------------------------------- construcción
def construir(hitl: bool = False):
    g = StateGraph(Estado)
    g.add_node("supervisor", supervisor)
    for nombre, fn in [("extractor", extractor), ("auditor", auditor_nodo), ("reflexion", reflexion),
                       ("trazabilidad", trazabilidad), ("critico", critico), ("cierre", cierre)]:
        g.add_node(nombre, fn)
        if nombre != "cierre":
            g.add_edge(nombre, "supervisor")
    g.add_edge("cierre", END)
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", siguiente,
                            ["extractor", "auditor", "reflexion", "trazabilidad", "critico", "cierre", END])
    if hitl:   # human-in-the-loop: se para antes de cerrar el informe
        return g.compile(checkpointer=MemorySaver(), interrupt_before=["cierre"])
    return g.compile()


def ejecutar(ruta_documento: str | None = None) -> Estado:
    return construir().invoke({"ruta_documento": ruta_documento or ""}, {"recursion_limit": 50})
