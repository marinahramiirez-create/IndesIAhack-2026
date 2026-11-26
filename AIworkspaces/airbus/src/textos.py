"""
Textos en dos idiomas (es / en).

El pipeline guarda los hallazgos como DATOS (qué falta, qué límite se incumple, qué palabra es vaga...) y aquí se
redactan las frases en el idioma que elija el usuario en la app. Así toda la página cambia de idioma, no solo las etiquetas.
"""

VEREDICTO = {
    "es": {"Cumple": "Cumple", "No cumple": "No cumple", "Revisar": "Revisar", "No aplica": "No aplica"},
    "en": {"Cumple": "Compliant", "No cumple": "Non-compliant", "Revisar": "Review", "No aplica": "Not applicable"},
}

VAGO = {
    "es": {"periodicidad": "periodicidad sin definir", "plazo": "plazo sin definir",
           "verbo": "verbo no obligatorio / condicional", "subjetivo": "criterio subjetivo"},
    "en": {"periodicidad": "undefined periodicity", "plazo": "undefined deadline",
           "verbo": "non-mandatory / conditional verb", "subjetivo": "subjective criterion"},
}

PARAMETRO_EN = {
    "plazo de notificación a la autoridad": "reporting deadline to the authority",
    "tiempo de recuperación tras incidente": "recovery time after an incident",
    "retención de registros de incidentes y riesgos": "retention of incident and risk records",
    "retención de registros de personal": "retention of personnel records",
    "periodicidad de revisión del análisis de riesgos": "risk assessment review periodicity",
    "periodicidad de evaluación del ISMS": "ISMS assessment periodicity",
}


def v(veredicto: str, lang: str) -> str:
    return VEREDICTO[lang].get(veredicto, veredicto)


def justificacion(det: dict, lang: str = "es") -> str:
    es = lang == "es"
    if det.get("no_aplica"):
        return ("El requisito no trata de seguridad de la información: fuera del alcance de Part-IS." if es else
                "The requirement does not address information security: out of the scope of Part-IS.")
    p = []
    if det.get("dudosos"):
        p.append(("Juicios del LLM no coincidentes sobre: " if es else "LLM judgements disagree on: ")
                 + ", ".join(x[lang] for x in det["dudosos"]) + ".")
    viol = []
    for x in det.get("violaciones", []):
        if x["tipo"] == "numerico":
            if es:
                viol.append(f"{x['es']}: el requisito fija «{x['valor']}» y la norma exige "
                            f"{'como máximo' if x['op'] == '<=' else 'como mínimo'} {x['lim_es']}")
            else:
                viol.append(f"{x['en']}: the requirement sets “{x['valor']}” and the rule requires "
                            f"{'at most' if x['op'] == '<=' else 'at least'} {x['lim_en']}")
        else:
            viol.append(f"{x[lang]}: «{x['valor']}»" if es else f"{x[lang]}: “{x['valor']}”")
    if viol:
        p.append(("Incumple un límite de la norma: " if es else "Breaches a limit set by the rule: ") + "; ".join(viol) + ".")
    if det.get("faltan"):
        p.append(("No define: " if es else "Does not define: ") + ", ".join(x[lang] for x in det["faltan"]) + ".")
    if det.get("vagos"):
        q = ("«{}»" if es else "“{}”")
        p.append(("Redacción no verificable (" if es else "Wording cannot be verified (")
                 + "; ".join(f"{VAGO[lang][x['tipo']]}: {q.format(x['palabra'])}" for x in det["vagos"]) + ").")
    if det.get("veredicto") == "Cumple":
        if det.get("evidencias"):
            p.append(("Recoge los elementos que exige la cláusula — " if es else "Covers the elements required by the clause — ")
                     + "; ".join(f"{x[lang]}: «{x['cita']}»" for x in det["evidencias"]) + ".")
        else:
            p.append(("Recoge los elementos que exige la cláusula: " if es else "Covers the elements required by the clause: ")
                     + ", ".join(x[lang] for x in det.get("elementos", [])) + ".")
    llm = det.get("llm")
    if llm:
        if llm["tipo"] == "reordeno":
            p.append((f"El LLM reordenó la búsqueda: {llm['de']} → {llm['a']}." if es else
                      f"The LLM re-ranked the retrieval: {llm['de']} → {llm['a']}.")
                     + (f" ({llm['motivo']})" if llm.get("motivo") else ""))
        elif llm["tipo"] == "ninguna":
            p.append("El LLM no ve obligación aplicable entre las candidatas." if es else
                     "The LLM sees no applicable obligation among the candidates.")
        else:
            p.append(("LLM no disponible: " if es else "LLM unavailable: ") + llm.get("motivo", ""))
    if det.get("revisar_por_reflexion"):
        p.append("Confianza baja tras la reflexión → revisión humana." if es else
                 "Low confidence after reflection → human review.")
    if det.get("clausula_inexistente"):
        p.append("Cláusula citada inexistente." if es else "Cited clause does not exist.")
    return " ".join(p)


def reflexion(r: dict | None, lang: str = "es") -> str:
    if not r:
        return ""
    if lang == "es":
        coma = lambda x: f"{x:.2f}".replace(".", ",")   # noqa: E731  (decimales con coma en español)
        t = (f"Confianza baja ({coma(r['conf_antes'])}) con {r['ob_antes']}; se reformuló la búsqueda → "
             f"{r['ob_despues']} ({coma(r['conf_despues'])}).")
        return t + (" Se mantiene el juicio inicial." if r.get("mantiene") else "")
    t = (f"Low confidence ({r['conf_antes']}) with {r['ob_antes']}; the query was reformulated → "
         f"{r['ob_despues']} ({r['conf_despues']}).")
    return t + (" The initial judgement is kept." if r.get("mantiene") else "")


def parametro(nombre: str, lang: str) -> str:
    return nombre if lang == "es" else PARAMETRO_EN.get(nombre, nombre)


def contradiccion(c, lang: str) -> str:
    if lang == "es":
        return f"{c.req_a} fija {c.valor_a} y {c.req_b} fija {c.valor_b} para «{c.parametro}»."
    return f"{c.req_a} sets {c.valor_a} and {c.req_b} sets {c.valor_b} for “{parametro(c.parametro, 'en')}”."


def homogeneidad(h, lang: str) -> str:
    m = []
    if h.escueto:
        m.append(f"mucho más escueto que su sección ({h.palabras} palabras frente a {h.media:.0f} de media)" if lang == "es"
                 else f"much shorter than its section ({h.palabras} words vs. {h.media:.0f} on average)")
    if h.sin_criterio:
        m.append("sin criterio verificable (plazo, cifra o responsable)" if lang == "es"
                 else "no verifiable criterion (deadline, figure or owner)")
    return "; ".join(m)


def traza(paso: dict, lang: str) -> str:
    d, k, es = paso.get("datos", {}), paso["clave"], lang == "es"
    if k == "extractor":
        return f"Extractor: {d['n']} requisitos extraídos del documento" if es else f"Extractor: {d['n']} requirements extracted from the document"
    if k == "auditor":
        juez = {"es": {"llm": "reglas + LLM (autoconsistencia)", "reglas": "reglas (sin LLM configurado)"},
                "en": {"llm": "rules + LLM (self-consistency)", "reglas": "rules (no LLM configured)"}}[lang][d["juez"]]
        return f"Auditor: {d['n']} requisitos juzgados · juez: {juez}" if es else f"Auditor: {d['n']} requirements judged · judge: {juez}"
    if k == "reflexion":
        return (f"Reflexión: {d['n']} hallazgos re-evaluados ({d['cambios']})" if es else
                f"Reflection: {d['n']} findings re-assessed ({d['cambios']})")
    if k == "trazabilidad":
        return (f"Trazabilidad: citas verificadas contra la normativa; cobertura {d['cubiertas']}/{d['total']} reglas IS.I.OR" if es else
                f"Traceability: citations checked against the regulation; coverage {d['cubiertas']}/{d['total']} IS.I.OR rules")
    if k == "critico":
        return (f"Crítico: {d['contra']} contradicciones y {d['homo']} requisitos con detalle insuficiente" if es else
                f"Critic: {d['contra']} contradictions and {d['homo']} requirements with insufficient detail")
    if k == "cierre":
        return "Cierre: informe listo" if es else "Close: report ready"
    return k


# ---------------------------------------------------------------- textos fijos de la interfaz
UI = {
    "es": {
        "eyebrow": "IndesIAhack 2026 · Reto Airbus Defence and Space",
        "titulo": "Verificación de cumplimiento normativo · EASA Part-IS",
        "sub": "Cada requisito del documento se contrasta con la cláusula de la norma que le aplica. La IA propone; el revisor decide.",
        "pill_norma": "Normativa: Reg. (UE) 2023/203 · 2022/1645", "requisitos": "requisitos", "juez": "Juez",
        "juez_llm": "reglas + LLM", "juez_reglas": "reglas (sin LLM)", "revisados": "revisados",
        "requiere_revision": "Requiere revisión",
        "m_f1": "F1 detección de incumplimientos", "m_ref_f1": "Referencia ≥ 0,80 ·",
        "m_f1s": "F1 señalados (No cumple + Revisar)", "m_f1s_ref": "Lo que llega al revisor",
        "m_traz": "Hallazgos enlazados a su regla", "m_traz_ref": "Referencia ≥ 90 % ·",
        "m_cob": "Cobertura reglas IS.I.OR", "m_cob_ref": "Reglas IR tocadas por el documento",
        "ok": "✓ cumple", "ko": "✗ por debajo",
        "menu": "Menú",
        "nav": {"metricas": "Métricas", "hallazgos": "Hallazgos", "consistencia": "Consistencia",
                "cobertura": "Cobertura", "agentes": "Agentes y métricas"},
        "s0": "Métricas de la auditoría",
        "g_titulo": "Visión gerencial de las auditorías",
        "g_nota": "Cartera simulada (datos sintéticos) más la auditoría actual, AUD-2026-031, que es real y cambia con cada validación del revisor.",
        "g_estados": {"Completa": "Completas", "Pendiente": "Pendientes", "No asegurada": "No aseguradas"},
        "g_estado1": {"Completa": "Completa", "Pendiente": "Pendiente", "No asegurada": "No asegurada"},
        "g_def": "Completa: informe de la IA validado al 100 % por un revisor · Pendiente: la IA aún no ha emitido el informe · No asegurada: informe emitido sin validación humana completa.",
        "g_de": "de", "g_auditorias": "auditorías", "g_dias": "días",
        "g_tiempo": "Antigüedad media de las abiertas", "g_fuera": "{n} fuera de plazo (más de {d} días)",
        "g_por_norma": "Estado de las auditorías por norma", "g_n": "Nº de auditorías",
        "g_antig": "Tiempo que llevan abiertas", "g_antig_ayuda": "Auditorías pendientes y no aseguradas. Plazo objetivo: {d} días.",
        "g_plazo": "fuera de plazo",
        "g_valid": "Validaciones humanas por semana", "g_valid_ayuda": "Requisitos validados por un revisor (aprobados o corregidos) en toda la cartera.",
        "g_curso": "semana en curso", "g_semana": "Semana del",
        "g_acuerdo": "Acuerdo IA–revisor", "g_acuerdo_ayuda": "validaciones en que el revisor aprobó la propuesta de la IA",
        "g_cobval": "Requisitos validados", "g_cobval_ayuda": "de todos los requisitos de la cartera",
        "g_cambios": "Cambios de norma", "g_cambios_ayuda": "Fecha de aplicación pública. «Por re-evaluar»: auditorías abiertas hechas contra la versión anterior de la norma (simulado).",
        "g_c_fecha": "Fecha", "g_c_norma": "Norma", "g_c_cambio": "Cambio", "g_c_afect": "Por re-evaluar",
        "g_actual": "Auditoría actual · AUD-2026-031",
        "s1": "Hallazgos por requisito", "estado": "Estado", "regla": "Regla", "todas": "Todas", "pendientes": "Solo pendientes",
        "ayuda_tabla": "Marca la casilla de la izquierda de una fila para abrir su detalle en el panel lateral y decidir.",
        "guardado": "{rid}: decisión guardada · {v}",
        "c_req": "Requisito", "c_regla": "Regla", "c_estado": "Estado", "c_conf": "Confianza", "c_rev": "Revisado",
        "c_just": "Justificación", "en_detalle": "Requisito en detalle", "sin_regla": "sin regla",
        "requisito": "Requisito", "confianza": "confianza", "juez_min": "juez", "ia_proponia": "la IA proponía",
        "justificacion": "Justificación.", "faltan": "Elementos exigidos que faltan:", "reflexion": "Bucle de reflexión",
        "autocons": "Autoconsistencia LLM", "regla_aplicable": "Regla aplicable",
        "fuente": "Fuente", "fuente_es": "Texto oficial en español · Reglamento de Ejecución (UE) 2023/203, anexo II, DO L 31 de 2.2.2023 (EUR-Lex)",
        "fuente_en_fallback": "Original en inglés · EASA Easy Access Rules (no hay versión oficial en español)",
        "fuente_en": "Original en inglés · EASA Easy Access Rules for Information Security (rev. diciembre 2025)",
        "btn_eurlex": "Reglamento en EUR-Lex (ES) ↗", "btn_easa": "en EASA (EN) ↗",
        "completo": "Texto completo de {c} (oficial en español)", "otro_idioma": "Ver el original en inglés (EASA Easy Access Rules)",
        "clausula_completa": "Cláusula completa:", "nota_idioma": "El auditor compara en inglés porque el documento de requisitos está en inglés.",
        "rag": "Detalle técnico de la recuperación (RAG)", "rag_txt": "Obligaciones candidatas y su puntuación BM25: ",
        "sin_regla_hd": "Sin regla aplicable",
        "sin_regla_bd": "El requisito no trata de seguridad de la información: queda fuera del alcance de Part-IS.",
        "decision": "Decisión del revisor", "hitl": "humano en el bucle", "aprobar": "Aprobar propuesta",
        "veredicto_final": "Veredicto final", "comentario": "Comentario (opcional)", "guardar": "Guardar corrección",
        "s2": "Matriz requisitos × reglas",
        "s2_ayuda": "Qué requisito se apoya en qué regla y con qué resultado. Una columna vacía es una regla sin cubrir.",
        "s3": "Consistencia del documento", "contradicciones": "Contradicciones entre requisitos",
        "sin_contra": "No se han detectado contradicciones.", "frente": "frente a",
        "homo": "Homogeneidad del detalle", "homo_ayuda": "Requisitos mucho más escuetos que el resto de su sección o sin criterio verificable.",
        "homo_cta": "Marca una fila para revisar el requisito.", "revisar_req": "Revisar {rid}",
        "palabras": "Palabras", "motivo": "Motivo",
        "s4": "Cobertura de la normativa", "s4_ayuda": "Reglas obligatorias (IR) de Part-IS para organizaciones (IS.I.OR) y qué requisitos las cubren.",
        "clausula": "Cláusula", "titulo_col": "Título", "requisitos_col": "Requisitos", "cubierta": "Cubierta",
        "titulos_fuente": "Títulos: texto oficial en español del Reglamento de Ejecución (UE) 2023/203, DO L 31 de 2.2.2023.",
        "s5": "Arquitectura agéntica (LangGraph)",
        "pasos": ["Supervisor", "Extractor", "Auditor", "Reflexión", "Trazabilidad", "Crítico", "Revisión humana", "Cierre"],
        "eval": "Evaluación contra el gold set", "metrica": "Métrica",
        "m_estricta": "Detección estricta (No cumple)", "m_senal": "Detección señalados (No cumple + Revisar)",
        "m_contra": "Contradicciones",
        "traz_txt": "Trazabilidad: {t} de los hallazgos citan la cláusula del gold · exactitud del veredicto: {e}",
        "s6": "Exportar informe", "s6_ayuda": "Informe HTML autocontenido con el estado actual, incluidas las decisiones del revisor.",
        "desc_html": "Descargar informe HTML", "desc_csv": "Descargar hallazgos CSV",
        "inf_titulo": "Informe de auditoría de cumplimiento · EASA Part-IS", "inf_proto": "INDESIAHACK 2026 · PROTOTIPO DEL EQUIPO",
        "generado": "Generado", "hallazgos": "Hallazgos", "texto": "Texto", "ninguna": "Ninguna",
        "pie": "Prototipo del equipo para IndesIAhack 2026 · datos sintéticos y normativa pública de EASA · no es una herramienta oficial de Airbus",
        "no_datos": "Todavía no hay auditoría. En la terminal, dentro de la carpeta airbus/, ejecuta:",
        "nota_req": "El texto del requisito se muestra en su idioma original (inglés): es la evidencia auditada.",
    },
    "en": {
        "eyebrow": "IndesIAhack 2026 · Airbus Defence and Space challenge",
        "titulo": "Regulatory compliance verification · EASA Part-IS",
        "sub": "Each requirement in the document is checked against the clause of the regulation that applies to it. AI proposes; the reviewer decides.",
        "pill_norma": "Regulation: (EU) 2023/203 · 2022/1645", "requisitos": "requirements", "juez": "Judge",
        "juez_llm": "rules + LLM", "juez_reglas": "rules (no LLM)", "revisados": "reviewed",
        "requiere_revision": "Needs review",
        "m_f1": "Non-compliance detection F1", "m_ref_f1": "Target ≥ 0.80 ·",
        "m_f1s": "Flagged F1 (Non-compliant + Review)", "m_f1s_ref": "What reaches the reviewer",
        "m_traz": "Findings linked to their rule", "m_traz_ref": "Target ≥ 90 % ·",
        "m_cob": "IS.I.OR rule coverage", "m_cob_ref": "IR rules addressed by the document",
        "ok": "✓ met", "ko": "✗ below target",
        "menu": "Menu",
        "nav": {"metricas": "Metrics", "hallazgos": "Findings", "consistencia": "Consistency",
                "cobertura": "Coverage", "agentes": "Agents & metrics"},
        "s0": "Audit metrics",
        "g_titulo": "Management view of audits",
        "g_nota": "Simulated portfolio (synthetic data) plus the current audit, AUD-2026-031, which is real and changes with every reviewer validation.",
        "g_estados": {"Completa": "Complete", "Pendiente": "Pending", "No asegurada": "Not assured"},
        "g_estado1": {"Completa": "Complete", "Pendiente": "Pending", "No asegurada": "Not assured"},
        "g_def": "Complete: AI report 100 % validated by a reviewer · Pending: the AI has not issued its report yet · Not assured: report issued without full human validation.",
        "g_de": "of", "g_auditorias": "audits", "g_dias": "days",
        "g_tiempo": "Average age of open audits", "g_fuera": "{n} overdue (more than {d} days)",
        "g_por_norma": "Audit status by standard", "g_n": "No. of audits",
        "g_antig": "How long they have been open", "g_antig_ayuda": "Pending and not-assured audits. Target: {d} days.",
        "g_plazo": "overdue",
        "g_valid": "Human validations per week", "g_valid_ayuda": "Requirements validated by a reviewer (approved or corrected) across the portfolio.",
        "g_curso": "current week", "g_semana": "Week of",
        "g_acuerdo": "AI–reviewer agreement", "g_acuerdo_ayuda": "validations where the reviewer approved the AI proposal",
        "g_cobval": "Requirements validated", "g_cobval_ayuda": "of all requirements in the portfolio",
        "g_cambios": "Regulatory changes", "g_cambios_ayuda": "Public date of application. \"To re-assess\": open audits run against the previous version of the standard (simulated).",
        "g_c_fecha": "Date", "g_c_norma": "Standard", "g_c_cambio": "Change", "g_c_afect": "To re-assess",
        "g_actual": "Current audit · AUD-2026-031",
        "s1": "Findings per requirement", "estado": "Status", "regla": "Rule", "todas": "All", "pendientes": "Pending only",
        "ayuda_tabla": "Tick the box on the left of a row to open its details in the side panel and decide.",
        "guardado": "{rid}: decision saved · {v}",
        "c_req": "Requirement", "c_regla": "Rule", "c_estado": "Status", "c_conf": "Confidence", "c_rev": "Reviewed",
        "c_just": "Rationale", "en_detalle": "Requirement in detail", "sin_regla": "no rule",
        "requisito": "Requirement", "confianza": "confidence", "juez_min": "judge", "ia_proponia": "AI proposed",
        "justificacion": "Rationale.", "faltan": "Required elements missing:", "reflexion": "Reflection loop",
        "autocons": "LLM self-consistency", "regla_aplicable": "Applicable rule",
        "fuente": "Source", "fuente_es": "Official Spanish text · Implementing Regulation (EU) 2023/203, Annex II, OJ L 31, 2.2.2023 (EUR-Lex)",
        "fuente_en_fallback": "English original · EASA Easy Access Rules",
        "fuente_en": "English original · EASA Easy Access Rules for Information Security (rev. December 2025)",
        "btn_eurlex": "Regulation on EUR-Lex (ES) ↗", "btn_easa": "on EASA (EN) ↗",
        "completo": "Full text of {c} (EASA, English)", "otro_idioma": "See the official Spanish text (OJ of the EU)",
        "clausula_completa": "Full clause:", "nota_idioma": "Spanish text: Implementing Regulation (EU) 2023/203, OJ L 31, 2.2.2023.",
        "rag": "Retrieval technical details (RAG)", "rag_txt": "Candidate obligations and their BM25 score: ",
        "sin_regla_hd": "No applicable rule",
        "sin_regla_bd": "The requirement does not address information security: it is out of the scope of Part-IS.",
        "decision": "Reviewer decision", "hitl": "human in the loop", "aprobar": "Approve proposal",
        "veredicto_final": "Final verdict", "comentario": "Comment (optional)", "guardar": "Save correction",
        "s2": "Requirements × rules matrix",
        "s2_ayuda": "Which requirement relies on which rule, and with what result. An empty column is an uncovered rule.",
        "s3": "Document consistency", "contradicciones": "Contradictions between requirements",
        "sin_contra": "No contradictions detected.", "frente": "vs.",
        "homo": "Homogeneity of detail", "homo_ayuda": "Requirements much shorter than the rest of their section or without a verifiable criterion.",
        "homo_cta": "Tick a row to review the requirement.", "revisar_req": "Review {rid}",
        "palabras": "Words", "motivo": "Reason",
        "s4": "Regulation coverage", "s4_ayuda": "Mandatory Part-IS rules (IR) for organisations (IS.I.OR) and which requirements cover them.",
        "clausula": "Clause", "titulo_col": "Title", "requisitos_col": "Requirements", "cubierta": "Covered",
        "titulos_fuente": "Titles: EASA Easy Access Rules for Information Security (English original).",
        "s5": "Agentic architecture (LangGraph)",
        "pasos": ["Supervisor", "Extractor", "Auditor", "Reflection", "Traceability", "Critic", "Human review", "Close"],
        "eval": "Evaluation against the gold set", "metrica": "Metric",
        "m_estricta": "Strict detection (Non-compliant)", "m_senal": "Flagged detection (Non-compliant + Review)",
        "m_contra": "Contradictions",
        "traz_txt": "Traceability: {t} of findings cite the gold clause · verdict accuracy: {e}",
        "s6": "Export report", "s6_ayuda": "Self-contained HTML report with the current state, including the reviewer's decisions.",
        "desc_html": "Download HTML report", "desc_csv": "Download findings CSV",
        "inf_titulo": "Compliance audit report · EASA Part-IS", "inf_proto": "INDESIAHACK 2026 · TEAM PROTOTYPE",
        "generado": "Generated", "hallazgos": "Findings", "texto": "Text", "ninguna": "None",
        "pie": "Team prototype for IndesIAhack 2026 · synthetic data and public EASA regulation · not an official Airbus tool",
        "no_datos": "No audit yet. In the terminal, inside the airbus/ folder, run:",
        "nota_req": "",
    },
}
