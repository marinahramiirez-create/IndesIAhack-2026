"""
Genera datos de prueba que imitan lo que dará Airbus el día del reto:

  salida/documento_requisitos.docx   documento técnico a auditar (requisitos con ID, en inglés como la normativa)
  salida/documento_requisitos.md     el mismo documento en texto (para leerlo rápido)
  salida/gold.csv                    gold set: veredicto esperado + cláusula + tipo de defecto por requisito
  salida/gold_contradicciones.csv    pares de requisitos que se contradicen

Defectos inyectados a propósito (como el gold set real):
  - numérico: plazo o retención fuera de lo que marca Part-IS (72 h, 5 años)
  - elemento_ausente: falta algo que la cláusula exige (p. ej. criterio de severidad)
  - redaccion_vaga: "periodically", "as soon as practicable", "may"... sin criterio verificable
  - contradicción: dos requisitos fijan valores distintos para lo mismo
  - trampa: dos valores distintos que NO son contradicción (registros de personal 3 años vs registros de incidentes 5 años)

Ejecutar desde la carpeta airbus/:
    python datos_sinteticos/generar.py
"""
from pathlib import Path

import pandas as pd

SALIDA = Path(__file__).resolve().parent / "salida"

# (id, sección, texto, veredicto_gold, cláusula_gold, apartado, tipo_defecto, motivo)
REQUISITOS = [
    # 1 Governance
    ("REQ-001", "1 Governance and ISMS",
     "The organisation shall establish an information security policy, approved by the accountable manager, setting out the overall principles of the organisation with regard to the potential impact of information security risks on aviation safety.",
     "Cumple", "IS.I.OR.200", "(a)(1)", "", ""),
    ("REQ-002", "1 Governance and ISMS",
     "The organisation shall document all key ISMS processes, procedures, roles and responsibilities in the Information Security Management Manual (ISMM) and shall maintain a process for amending that documentation.",
     "Cumple", "IS.I.OR.200", "(c)", "", ""),
    ("REQ-003", "1 Governance and ISMS",
     "The ISMM shall include a statement signed by the accountable manager confirming that the organisation will at all times work in accordance with Part-IS and with the ISMM.",
     "Cumple", "IS.I.OR.250", "(a)(1)", "", ""),
    # 2 Risk
    ("REQ-004", "2 Information security risk management",
     "The organisation shall identify all elements that could be exposed to information security risks, including its activities, facilities, resources and services, and the equipment, systems, data and information supporting them.",
     "Cumple", "IS.I.OR.205", "(a)", "", ""),
    ("REQ-005", "2 Information security risk management",
     "The organisation shall identify the interfaces it has with other organisations which could result in mutual exposure to information security risks.",
     "Cumple", "IS.I.OR.205", "(b)", "", ""),
    ("REQ-006", "2 Information security risk management",
     "For each identified information security risk, the organisation shall assign a risk level according to a predefined classification that takes into account the likelihood of occurrence of the threat scenario and the severity of its safety consequences.",
     "Cumple", "IS.I.OR.205", "(c)", "", ""),
    ("REQ-007", "2 Information security risk management",
     "Each identified risk shall be assigned a level (low, medium or high) using the corporate risk matrix.",
     "No cumple", "IS.I.OR.205", "(c)", "elemento_ausente",
     "La clasificación no considera la probabilidad de ocurrencia ni la severidad de las consecuencias para la seguridad."),
    ("REQ-008", "2 Information security risk management",
     "The risk assessment shall be reviewed and updated whenever there is a change in the elements or interfaces, a change in the knowledge used to classify risks, or lessons learnt from information security incidents, and in any case at least every 12 months.",
     "Cumple", "IS.I.OR.205", "(d)", "", ""),
    ("REQ-009", "2 Information security risk management",
     "The risk assessment shall be reviewed every 36 months.",
     "No cumple", "IS.I.OR.205", "(d)", "elemento_ausente",
     "Solo revisión por calendario: no se revisa ante cambios ni lecciones aprendidas de incidentes."),
    ("REQ-010", "2 Information security risk management",
     "The organisation shall develop risk treatment measures for all unacceptable risks, implement them in a timely manner and verify their continued effectiveness.",
     "Cumple", "IS.I.OR.210", "(a)", "", ""),
    ("REQ-011", "2 Information security risk management",
     "Risk treatment measures shall be put in place for all high risks.",
     "No cumple", "IS.I.OR.210", "(a)", "elemento_ausente",
     "No se comprueba la eficacia continuada de las medidas."),
    ("REQ-012", "2 Information security risk management",
     "The outcome of the risk assessment, the corresponding threat scenarios and the measures to be implemented shall be communicated to the ISMS manager and affected personnel, and to interfacing organisations sharing the risk.",
     "Cumple", "IS.I.OR.210", "(b)", "", ""),
    # 3 Reporting
    ("REQ-013", "3 Reporting",
     "The organisation shall establish an internal reporting scheme to collect and evaluate information security events and to identify incidents, vulnerabilities and their causes.",
     "Cumple", "IS.I.OR.215", "(a)-(b)", "", ""),
    ("REQ-014", "3 Reporting",
     "Contracted organisations which may expose the organisation to information security risks shall be required to report information security events to the organisation using the procedures defined in the contractual arrangements.",
     "Cumple", "IS.I.OR.215", "(c)", "", ""),
    ("REQ-015", "3 Reporting",
     "Significant information security incidents shall be notified to the competent authority as soon as they are known, and a report shall be submitted no later than 72 hours from the time the condition has been known.",
     "Cumple", "IS.I.OR.230", "(c)(1)-(2)", "", ""),
    ("REQ-016", "3 Reporting",
     "Information security incidents affecting aircraft systems shall be reported to the competent authority and to the design approval holder within 5 working days.",
     "No cumple", "IS.I.OR.230", "(c)(1)-(2)", "numerico",
     "5 días supera el máximo de 72 horas."),
    ("REQ-017", "3 Reporting",
     "A follow-up report describing the actions taken to recover from the incident and to prevent similar incidents shall be submitted to the competent authority as soon as those actions have been identified.",
     "Cumple", "IS.I.OR.230", "(c)(3)", "", ""),
    # 4 Detection, response, recovery
    ("REQ-018", "4 Detection, response and recovery",
     "The organisation shall implement monitoring measures able to detect deviations from predetermined functional performance baselines and to trigger warnings that activate the response measures.",
     "Cumple", "IS.I.OR.220", "(a)", "", ""),
    ("REQ-019", "4 Detection, response and recovery",
     "Security monitoring shall be performed on critical servers.",
     "No cumple", "IS.I.OR.220", "(a)", "elemento_ausente",
     "No define líneas base ni avisos que activen la respuesta."),
    ("REQ-020", "4 Detection, response and recovery",
     "Upon a warning, the organisation shall activate predefined response resources and courses of action, contain the spread of the attack and control the failure mode of the affected elements.",
     "Cumple", "IS.I.OR.220", "(b)", "", ""),
    ("REQ-021", "4 Detection, response and recovery",
     "The organisation shall implement recovery measures to remove the condition that caused the incident and reach a safe state of the affected elements within a recovery time of 4 hours.",
     "Cumple", "IS.I.OR.220", "(c)", "", ""),
    ("REQ-022", "4 Detection, response and recovery",
     "Affected ground systems shall be restored within 24 hours after an information security incident.",
     "No cumple", "IS.I.OR.220", "(c)", "elemento_ausente",
     "No elimina la causa ni exige alcanzar un estado seguro (y contradice el tiempo de recuperación de REQ-021)."),
    # 5 Findings, contracting, changes
    ("REQ-023", "5 Findings, contracting and changes",
     "Upon notification of findings by the competent authority, the organisation shall identify the root causes, define a corrective action plan and demonstrate the correction within the period agreed with the competent authority.",
     "Cumple", "IS.I.OR.225", "(a)-(b)", "", ""),
    ("REQ-024", "5 Findings, contracting and changes",
     "Findings notified by the competent authority shall be corrected as soon as practicable.",
     "No cumple", "IS.I.OR.225", "(a)-(b)", "redaccion_vaga",
     "Sin análisis de causa raíz, sin plan de acciones correctivas y sin plazo acordado."),
    ("REQ-025", "5 Findings, contracting and changes",
     "When contracting ISMS activities, the organisation shall ensure that the contracted organisation complies with Part-IS and works under the oversight of the organisation, and that the competent authority can access the contracted organisation upon request.",
     "Cumple", "IS.I.OR.235", "(a)-(b)", "", ""),
    ("REQ-026", "5 Findings, contracting and changes",
     "ISMS activities may be outsourced to external providers.",
     "No cumple", "IS.I.OR.235", "(a)-(b)", "redaccion_vaga",
     "No exige supervisión del contratista ni acceso de la autoridad."),
    ("REQ-027", "5 Findings, contracting and changes",
     "Changes to the ISMS not covered by the approved change procedure shall be approved by the competent authority before they are implemented.",
     "Cumple", "IS.I.OR.255", "(b)", "", ""),
    ("REQ-028", "5 Findings, contracting and changes",
     "Changes to the ISMS shall be notified to the competent authority within 30 days after implementation.",
     "No cumple", "IS.I.OR.255", "(b)", "elemento_ausente",
     "Notifica después del cambio; Part-IS exige aprobación previa."),
    # 6 Records
    ("REQ-029", "6 Record-keeping",
     "Records of identified risks, risk treatment measures, information security incidents and vulnerabilities shall be archived, traceable and retained for at least 5 years, using means that ensure integrity, authenticity and authorised access.",
     "Cumple", "IS.I.OR.245", "(a)(4)", "", ""),
    ("REQ-030", "6 Record-keeping",
     "Security event logs and incident records shall be retained for 2 years.",
     "No cumple", "IS.I.OR.245", "(a)(4)", "numerico",
     "2 años es inferior a los 5 años exigidos."),
    ("REQ-031", "6 Record-keeping",
     "Personnel qualification and experience records shall be retained while the person works for the organisation and for at least 3 years after the person has left.",
     "Cumple", "IS.I.OR.245", "(b)(1)", "", ""),
    # 7 Personnel
    ("REQ-032", "7 Personnel",
     "The accountable manager shall appoint a person or group of persons responsible for Part-IS compliance, who shall report directly to the accountable manager; the procedures shall define who deputises for that person in case of lengthy absence.",
     "Cumple", "IS.I.OR.240", "(b)", "", ""),
    ("REQ-033", "7 Personnel",
     "An Information Security Officer shall be appointed.",
     "No cumple", "IS.I.OR.240", "(b)", "elemento_ausente",
     "No reporta directamente al accountable manager ni define suplente."),
    ("REQ-034", "7 Personnel",
     "The organisation shall maintain a process to ensure that personnel performing information security tasks have the necessary competence, including annual security training.",
     "Cumple", "IS.I.OR.240", "(g)-(i)", "", ""),
    # 8 Continuous improvement
    ("REQ-035", "8 Continuous improvement",
     "The organisation shall assess the effectiveness and maturity of the ISMS using adequate performance indicators, on an annual calendar basis and following any information security incident.",
     "Cumple", "IS.I.OR.260", "(a)", "", ""),
    ("REQ-036", "8 Continuous improvement",
     "The ISMS shall be improved regularly.",
     "No cumple", "IS.I.OR.260", "(a)", "redaccion_vaga",
     "Sin indicadores de rendimiento ni calendario predefinido."),
    # 9 Requisitos fuera del alcance de Part-IS
    ("REQ-037", "9 General system requirements",
     "The maintenance planning tool shall display task cards in the user's preferred language.",
     "No aplica", "", "", "", ""),
    ("REQ-038", "9 General system requirements",
     "The hangar badge reader shall operate between -10 °C and +45 °C.",
     "No aplica", "", "", "", ""),
]

CONTRADICCIONES = [
    ("REQ-015", "REQ-016", "plazo de notificación a la autoridad", "72 horas vs 5 días laborables"),
    ("REQ-021", "REQ-022", "tiempo de recuperación", "4 horas vs 24 horas"),
    ("REQ-029", "REQ-030", "retención de registros de incidentes", "5 años vs 2 años"),
    ("REQ-008", "REQ-009", "periodicidad de revisión de riesgos", "12 meses vs 36 meses"),
]


def escribir_docx(ruta: Path):
    from docx import Document
    doc = Document()
    doc.add_heading("Information Security Requirements Specification", 0)
    doc.add_paragraph("Organisation: Demo Aero Maintenance (synthetic) · Document ISRS-001 · Rev. A")
    doc.add_paragraph("This specification defines the information security requirements applicable to the "
                      "organisation in order to comply with Regulation (EU) 2023/203 (Part-IS).")
    seccion = None
    for rid, sec, texto, *_ in REQUISITOS:
        if sec != seccion:
            doc.add_heading(sec, 1)
            seccion = sec
        p = doc.add_paragraph()
        p.add_run(f"{rid}  ").bold = True
        p.add_run(texto)
    doc.save(ruta)


def escribir_md(ruta: Path):
    lineas = ["# Information Security Requirements Specification", "",
              "Organisation: Demo Aero Maintenance (synthetic) · Document ISRS-001 · Rev. A", ""]
    seccion = None
    for rid, sec, texto, *_ in REQUISITOS:
        if sec != seccion:
            lineas += ["", f"## {sec}", ""]
            seccion = sec
        lineas.append(f"**{rid}** {texto}")
        lineas.append("")
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def main():
    SALIDA.mkdir(exist_ok=True)
    escribir_docx(SALIDA / "documento_requisitos.docx")
    escribir_md(SALIDA / "documento_requisitos.md")
    gold = pd.DataFrame(REQUISITOS, columns=["req_id", "seccion", "texto", "veredicto_gold", "clausula_gold",
                                             "apartado_gold", "tipo_defecto", "motivo_gold"])
    gold.drop(columns=["texto", "seccion"]).to_csv(SALIDA / "gold.csv", index=False)
    pd.DataFrame(CONTRADICCIONES, columns=["req_a", "req_b", "parametro", "detalle"]).to_csv(
        SALIDA / "gold_contradicciones.csv", index=False)
    print(f"{len(gold)} requisitos ({(gold.veredicto_gold == 'No cumple').sum()} incumplimientos, "
          f"{(gold.veredicto_gold == 'No aplica').sum()} fuera de alcance) y "
          f"{len(CONTRADICCIONES)} contradicciones → {SALIDA}")


if __name__ == "__main__":
    main()
