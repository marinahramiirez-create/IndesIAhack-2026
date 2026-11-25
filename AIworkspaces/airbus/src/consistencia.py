"""
Crítico de consistencia del documento (no necesita LLM).

1. Contradicciones: requisitos que fijan valores distintos para el MISMO parámetro
   (p. ej. "retención de registros de incidentes: 5 años" vs "2 años").
   El parámetro se reconoce por palabras clave; el valor (duración) lo extrae el código.
   Ojo a las trampas: "registros de personal 3 años" NO contradice "registros de incidentes 5 años"
   → son parámetros distintos.
2. Homogeneidad del detalle: requisitos mucho más escuetos que el resto de su sección o sin
   ningún criterio verificable (cifra, plazo, responsable).
"""
import re
from itertools import combinations

from src.auditor import duraciones

# parámetro → (patrones que deben aparecer TODOS, patrón que lo excluye)
PARAMETROS = {
    "plazo de notificación a la autoridad": ([r"report|notif", r"authorit"], r"follow-up|follow up|findings|change"),
    "tiempo de recuperación tras incidente": ([r"restor|recover"], None),
    "retención de registros de incidentes y riesgos": ([r"retain|retention|kept"], r"personnel|staff|qualification"),
    "retención de registros de personal": ([r"retain|retention|kept", r"personnel|staff|qualification"], None),
    "periodicidad de revisión del análisis de riesgos": ([r"review", r"risk"], None),
    "periodicidad de evaluación del ISMS": ([r"assess|evaluat", r"isms|effectiveness"], r"risk"),
}


def parametros_de(texto: str) -> list[str]:
    salida = []
    for nombre, (obligatorios, excluye) in PARAMETROS.items():
        if all(re.search(p, texto, re.I) for p in obligatorios) and not (excluye and re.search(excluye, texto, re.I)):
            salida.append(nombre)
    return salida


def contradicciones(requisitos: list[dict]) -> list[dict]:
    valores = []   # (parámetro, req, duración)
    for r in requisitos:
        ds = duraciones(r["texto"])
        if not ds:
            continue
        for p in parametros_de(r["texto"]):
            valores.append((p, r, ds[0]))
    salida = []
    for (pa, ra, da), (pb, rb, db) in combinations(valores, 2):
        if pa == pb and ra["req_id"] != rb["req_id"] and abs(da["horas"] - db["horas"]) > 1e-6:
            salida.append({
                "req_a": ra["req_id"], "req_b": rb["req_id"], "parametro": pa,
                "valor_a": da["texto"], "valor_b": db["texto"],
                "explicacion": f"{ra['req_id']} fija {da['texto']} y {rb['req_id']} fija {db['texto']} para «{pa}».",
            })
    return salida


def homogeneidad(requisitos: list[dict]) -> list[dict]:
    salida = []
    por_seccion: dict[str, list[int]] = {}
    for r in requisitos:
        por_seccion.setdefault(r.get("seccion", ""), []).append(len(r["texto"].split()))
    for r in requisitos:
        n = len(r["texto"].split())
        lens = por_seccion[r.get("seccion", "")]
        media = sum(lens) / len(lens)
        verificable = bool(duraciones(r["texto"]) or re.search(r"\d|accountable manager|competent authority", r["texto"], re.I))
        motivos = []
        if n < 0.5 * media and n < 15:
            motivos.append(f"mucho más escueto que su sección ({n} palabras frente a {media:.0f} de media)")
        if not verificable and n < 15:
            motivos.append("sin criterio verificable (plazo, cifra o responsable)")
        if motivos:
            salida.append({"req_id": r["req_id"], "palabras": n, "motivo": "; ".join(motivos)})
    return salida
