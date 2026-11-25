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
def juicio_reglas(req: dict, ob: dict) -> dict:
    texto = req["texto"]
    faltan, violaciones, vagos, resaltar = [], [], [], []

    for el in ob.get("elementos", []):
        if not _buscar(el["patrones"], texto):
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
        confianza = 0.85 if ob["score_bm25"] >= 10 else 0.6   # poca coincidencia → menos seguro

    partes = []
    if violaciones:
        partes.append("Incumple un límite de la norma: " + "; ".join(violaciones) + ".")
    if faltan:
        partes.append("No define: " + ", ".join(faltan) + ".")
    if vagos:
        partes.append("Redacción no verificable (" + "; ".join(vagos) + ").")
    if veredicto == "Cumple":
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

    candidatas = rag.buscar_obligaciones(consulta or req["texto"])
    ob = candidatas[0]
    jr = juicio_reglas(req, ob)
    if ob["score_bm25"] < 5:            # recuperación pobre: el juicio es poco fiable → reflexión
        jr["confianza"] = round(min(jr["confianza"], 0.45), 2)

    hallazgo = {**base, **jr, "obligacion_id": ob["id"], "clausula": ob["clausula"], "apartado": ob["apartado"],
                "tema": ob["tema"], "texto_norma": ob["texto_norma"], "score_recuperacion": round(ob["score_bm25"], 1),
                "candidatas": [f"{c['id']} ({c['score_bm25']:.1f})" for c in candidatas], "juez": "reglas",
                "llm_votos": [], "cita_verificada": True}

    if llm.disponible():
        hallazgo = _combinar_con_llm(hallazgo, req, candidatas)
    return hallazgo


def _combinar_con_llm(h: dict, req: dict, candidatas: list[dict]) -> dict:
    fr = rag.buscar_fragmentos(req["texto"], k=config.TOP_K, clausula=candidatas[0]["clausula"])
    votos, error = llm.juzgar(req, candidatas[:3], fr, n=config.JUICIOS_AUTOCONSISTENCIA)
    if not votos:
        h["justificacion"] += f" (LLM no disponible: {error})"
        return h
    h["llm_votos"] = [v.veredicto for v in votos]
    mayoritario = max(set(h["llm_votos"]), key=h["llm_votos"].count)
    unanimes = h["llm_votos"].count(mayoritario) == len(votos)
    elegido = next(v for v in votos if v.veredicto == mayoritario)

    # Verificador de citas: la cláusula debe estar entre las recuperadas y la cita debe existir literalmente
    citables = {c["clausula"] for c in candidatas} | {f["clausula"] for f in fr}
    textos_norma = " ".join([c["texto_norma"] for c in candidatas] + [f["texto"] for f in fr])
    cita_ok = elegido.clausula in citables and llm.cita_literal(elegido.cita_norma, textos_norma)

    veredicto = mayoritario
    conf = elegido.confianza if unanimes else min(elegido.confianza, 0.5)
    motivo_extra = ""
    if h["violaciones"]:                          # el código manda en los números
        veredicto, conf = "No cumple", max(conf, 0.9)
    elif {veredicto, h["veredicto"]} == {"Cumple", "No cumple"}:
        veredicto, conf = "Revisar", 0.4
        motivo_extra = f" Discrepancia: reglas = {h['veredicto']}, LLM = {mayoritario}."
    if not unanimes and veredicto != "No cumple":
        veredicto = "Revisar"
        motivo_extra += f" Los {len(votos)} juicios del LLM no coinciden ({', '.join(h['llm_votos'])})."
    if not cita_ok:
        veredicto = "Revisar"
        motivo_extra += " La cita del LLM no se encontró literalmente en la norma (verificador de citas)."

    ob = next((c for c in candidatas if c["clausula"] == elegido.clausula), candidatas[0])
    h.update({
        "veredicto": veredicto, "confianza": round(conf, 2), "juez": "reglas+LLM", "cita_verificada": cita_ok,
        "justificacion": elegido.justificacion + motivo_extra + " | Reglas: " + h["justificacion"],
        "clausula": elegido.clausula if cita_ok else h["clausula"],
        "apartado": elegido.apartado or ob["apartado"],
        "resaltar": h["resaltar"] + ([elegido.fragmento_requisito] if elegido.fragmento_requisito else []),
        "cita_llm": elegido.cita_norma,
    })
    return h
