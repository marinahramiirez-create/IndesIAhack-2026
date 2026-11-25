"""
Auditor de cumplimiento: requisito → veredicto (Cumple / No cumple / Revisar / No aplica) con cita a la cláusula.

Dos jueces que se complementan:
  1. Juez por reglas (siempre): comprueba con código lo verificable de la obligación recuperada
     - elementos obligatorios presentes (p. ej. "severidad" y "probabilidad" en la clasificación de riesgos)
     - límites numéricos (72 h, 5 años...): el número lo extrae y lo compara el CÓDIGO, nunca el LLM
     - formulaciones prohibidas (p. ej. notificar "after implementation" cuando se exige aprobación previa)
     - redacción vaga ("periodically", "may", "as soon as practicable") → no verificable → "Revisar"
  2. Juez LLM (si hay LLM en .env): lee requisito + obligaciones + texto de la norma y emite JSON validado
     con Pydantic. Se pide N veces (autoconsistencia): si los juicios discrepan → "Revisar".

Combinación: las violaciones numéricas detectadas por código mandan siempre. Si los dos jueces
discrepan (uno dice Cumple y el otro No cumple) → "Revisar" para el humano.
"""
import re

import config
from src import llm, rag

# ---------------------------------------------------------------- utilidades de texto
UNIDADES_H = {"hour": 1, "h": 1, "hr": 1, "day": 24, "working day": 24, "business day": 24, "week": 168,
              "month": 730, "year": 8760}
NUMEROS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "twelve": 12}
PATRON_DURACION = re.compile(
    r"\b(\d+(?:[.,]\d+)?|" + "|".join(NUMEROS) + r")\s*(working days?|business days?|hours?|hrs?|h|days?|weeks?|months?|years?)\b",
    re.I)

VAGUEDAD = [
    (r"\bperiodically\b|\bregularly\b|\bfrom time to time\b", "periodicidad sin definir"),
    (r"\bas soon as practicable\b|\bin due course\b|\bpromptly\b", "plazo sin definir"),
    (r"\bmay\b|\bshould\b|\bwhere possible\b|\bif feasible\b|\bas appropriate\b", "verbo no obligatorio / condicional"),
    (r"\badequate\b|\bsufficient\b|\bappropriate\b", "criterio subjetivo"),
]

# Para saber si un requisito es de seguridad de la información (si no, "No aplica" a Part-IS)
LEXICO_SEGURIDAD = re.compile(
    r"secur|isms|risk|incident|vulnerab|threat|attack|cyber|record|log|authority|accountable|audit|"
    r"monitor|personnel|contract|outsourc|polic|interface|finding|ismm|part-is|confidential|integrity", re.I)

# Sinónimos para reformular la consulta en el bucle de reflexión (sin LLM)
SINONIMOS = {
    r"restor": "recovery recover safe state recovery time",
    r"outsourc|provider|third part": "contracting contracted organisation oversight",
    r"\blog": "records retained retention",
    r"notif|inform": "report competent authority",
    r"officer|ciso|manager": "appoint person responsible accountable manager",
    r"improv": "continuous improvement performance indicators",
    r"train|aware": "competence personnel",
    r"matrix|level": "risk level classification severity likelihood",
}


def duraciones(texto: str) -> list[dict]:
    salida = []
    for m in PATRON_DURACION.finditer(texto):
        n = m.group(1).lower()
        n = NUMEROS.get(n, None) or float(n.replace(",", "."))
        unidad = m.group(2).lower().rstrip("s")
        unidad = {"hr": "hour", "h": "hour"}.get(unidad, unidad)
        horas = n * UNIDADES_H.get(unidad, UNIDADES_H.get(unidad.split()[-1], 1))
        salida.append({"texto": m.group(0), "horas": horas, "inicio": m.start(), "fin": m.end()})
    return salida


def _buscar(patrones: list[str], texto: str) -> re.Match | None:
    for p in patrones:
        m = re.search(p, texto, re.I)
        if m:
            return m
    return None


def es_aplicable(texto: str) -> bool:
    return bool(LEXICO_SEGURIDAD.search(texto))


def reformular(texto: str) -> str:
    extra = [v for k, v in SINONIMOS.items() if re.search(k, texto, re.I)]
    return texto + " " + " ".join(extra)


# ---------------------------------------------------------------- juez por reglas
def juicio_reglas(req: dict, ob: dict, presentes: dict | None = None) -> dict:
    """
    presentes (opcional, viene del LLM): {nombre_elemento: {"presente": bool, "cita": str, "dudoso": bool}}.
    Si se da, sustituye a las expresiones regulares para decidir qué elementos cubre el requisito
    (el LLM entiende sinónimos); el resto (límites numéricos, prohibidos, vaguedad) lo sigue haciendo el código.
    """
    texto = req["texto"]
    faltan, violaciones, vagos, resaltar, dudosos, evidencias = [], [], [], [], [], []

    for el in ob.get("elementos", []):
        if presentes and el["nombre"] in presentes:
            p = presentes[el["nombre"]]
            if p.get("dudoso"):
                dudosos.append(el["nombre"])
            if p["presente"]:
                evidencias.append(f"{el['nombre']}: «{p['cita']}»")
            else:
                faltan.append(el["nombre"])
        elif not _buscar(el["patrones"], texto):
            faltan.append(el["nombre"])

    for num in ob.get("numericos", []):
        for d in duraciones(texto):
            if (num["op"] == "<=" and d["horas"] > num["valor_horas"]) or \
               (num["op"] == ">=" and d["horas"] < num["valor_horas"]):
                violaciones.append(f"{num['nombre']}: el requisito fija «{d['texto']}» y la norma exige "
                                   f"{'como máximo' if num['op'] == '<=' else 'como mínimo'} {num['texto_limite']}")
                resaltar.append(d["texto"])

    for pr in ob.get("prohibidos", []):
        m = re.search(pr["patron"], texto, re.I)
        if m:
            violaciones.append(f"{pr['nombre']}: «{m.group(0)}»")
            resaltar.append(m.group(0))

    obligatorio = re.search(r"\bshall\b|\bmust\b", texto, re.I)
    for patron, motivo in VAGUEDAD:
        m = re.search(patron, texto, re.I)
        if not m:
            continue
        if motivo.startswith("verbo") and obligatorio:
            continue    # "shall ... which may expose": el requisito ya es obligatorio, el "may" es subordinado
        if re.search(re.escape(m.group(0)), ob.get("texto_norma", ""), re.I):
            continue    # la propia norma usa esa palabra ("adequate performance indicators")
        if m:
            vagos.append(f"{motivo}: «{m.group(0)}»")
            resaltar.append(m.group(0))

    if violaciones:
        veredicto, confianza = "No cumple", 0.9
    elif faltan:
        veredicto = "No cumple"
        confianza = 0.55 + 0.15 * min(len(faltan), 2) + (0.1 if vagos else 0)
    elif vagos:
        veredicto, confianza = "Revisar", 0.5
    else:
        veredicto = "Cumple"
        confianza = 0.85 if (presentes or ob["score_bm25"] >= 10) else 0.6   # poca coincidencia → menos seguro
    if dudosos and not violaciones:      # los juicios del LLM no coinciden en algún elemento → decide el humano
        veredicto, confianza = "Revisar", 0.5

    partes = []
    if dudosos and not violaciones:
        partes.append("Juicios del LLM no coincidentes sobre: " + ", ".join(dudosos) + ".")
    if violaciones:
        partes.append("Incumple un límite de la norma: " + "; ".join(violaciones) + ".")
    if faltan:
        partes.append("No define: " + ", ".join(faltan) + ".")
    if vagos:
        partes.append("Redacción no verificable (" + "; ".join(vagos) + ").")
    if veredicto == "Cumple":
        if evidencias:
            partes.append("Recoge los elementos que exige la cláusula — " + "; ".join(evidencias) + ".")
        else:
            partes.append("Recoge los elementos que exige la cláusula: "
                          + ", ".join(e["nombre"] for e in ob.get("elementos", [])) + ".")
    return {
        "veredicto": veredicto, "confianza": round(min(confianza, 0.95), 2),
        "justificacion": " ".join(partes),
        "faltan": faltan, "violaciones": violaciones, "vaguedad": vagos, "resaltar": resaltar,
    }


# ---------------------------------------------------------------- auditoría de un requisito
def auditar(req: dict, consulta: str | None = None) -> dict:
    """Devuelve el hallazgo de un requisito (todo lo que necesita la interfaz y la evaluación)."""
    base = {"req_id": req["req_id"], "texto": req["texto"], "seccion": req.get("seccion", ""),
            "ubicacion": req.get("ubicacion", ""), "consulta": consulta or req["texto"]}

    if not es_aplicable(req["texto"]):
        return {**base, "veredicto": "No aplica", "confianza": 0.8, "obligacion_id": "", "clausula": "",
                "apartado": "", "tema": "", "texto_norma": "", "score_recuperacion": 0.0,
                "justificacion": "El requisito no trata de seguridad de la información: fuera del alcance de Part-IS.",
                "resaltar": [], "faltan": [], "violaciones": [], "vaguedad": [], "candidatas": [], "juez": "reglas",
                "llm_votos": [], "cita_verificada": True}

    usa_llm = llm.disponible()
    # Con LLM se recuperan más candidatas: el LLM elige entre ellas (reordenación), nunca fuera de ellas
    candidatas = rag.buscar_obligaciones(consulta or req["texto"], k=config.TOP_K_LLM if usa_llm else config.TOP_K)
    ob, juez, nota_llm, presentes, votos = candidatas[0], "reglas", "", None, []

    if usa_llm:
        elegida, motivo = llm.elegir_obligacion(req, candidatas)
        if elegida == "ninguna":
            nota_llm = f"El LLM no ve obligación aplicable entre las candidatas ({motivo})."
        elif elegida:
            ob = next(c for c in candidatas if c["id"] == elegida)
            if ob is not candidatas[0]:
                nota_llm = f"El LLM reordenó la búsqueda: {candidatas[0]['id']} → {ob['id']} ({motivo})."
        presentes, votos, error = llm.evaluar_elementos(req, ob, n=config.JUICIOS_AUTOCONSISTENCIA)
        juez = "reglas + LLM" if presentes else "reglas"
        if not presentes and error:
            nota_llm += f" LLM no disponible: {error}."

    jr = juicio_reglas(req, ob, presentes)
    if ob["score_bm25"] < 5 and not presentes:   # recuperación pobre y sin LLM: poco fiable → reflexión
        jr["confianza"] = round(min(jr["confianza"], 0.45), 2)
    if nota_llm:
        jr["justificacion"] = (jr["justificacion"] + " " + nota_llm).strip()

    return {**base, **jr, "obligacion_id": ob["id"], "clausula": ob["clausula"], "apartado": ob["apartado"],
            "tema": ob["tema"], "texto_norma": ob["texto_norma"], "score_recuperacion": round(ob["score_bm25"], 1),
            "candidatas": [f"{c['id']} ({c['score_bm25']:.1f})" for c in candidatas], "juez": juez,
            "llm_votos": votos, "cita_verificada": True}
