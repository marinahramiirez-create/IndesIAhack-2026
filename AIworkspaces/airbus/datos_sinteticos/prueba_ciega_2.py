"""
Prueba ciega 2 (conjunto de VALIDACIÓN). Escrita el 25-nov-2026 ANTES de ajustar el juez por reglas y sin mirar
sus listas de palabras: solo a partir del texto de la norma (obligaciones IS.I.OR.200-260).

Regla de uso: las mejoras del juez se hacen mirando la prueba ciega 1 (prueba_ciega.py). Esta se usa SOLO para
medir. Si se cambia el juez mirando los fallos de esta prueba, deja de ser una medida honesta.

Ejecutar desde airbus/:
    python datos_sinteticos/prueba_ciega_2.py
    (PowerShell)
    $env:DIR_DATOS="datos_sinteticos/salida_ciega2"; $env:DOCUMENTO="documento_requisitos.md"; $env:DATABASE_URL="sqlite:///datos/prueba_ciega2.db"
    python -m src.pipeline
    Remove-Item Env:DIR_DATOS, Env:DOCUMENTO, Env:DATABASE_URL
"""
from pathlib import Path

import pandas as pd

SALIDA = Path(__file__).resolve().parent / "salida_ciega2"

# (id, texto, veredicto esperado, cláusula esperada)
REQUISITOS = [
    ("SEC-201", "Any information security incident that may affect aviation safety shall be notified to the competent "
                "authority no later than 72 hours after it has been identified.", "Cumple", "IS.I.OR.230"),
    ("SEC-202", "Significant cyber events shall be reported to the authority within one week.", "No cumple", "IS.I.OR.230"),
    ("SEC-203", "Once an incident has been notified, a follow-up report describing the recovery and preventive actions "
                "taken shall be submitted to the authority.", "Cumple", "IS.I.OR.230"),
    ("SEC-204", "The organisation shall maintain an information security policy describing its general principles "
                "regarding the potential effects of security risks on aviation safety.", "Cumple", "IS.I.OR.200"),
    ("SEC-205", "An IT policy shall be written.", "No cumple", "IS.I.OR.200"),
    ("SEC-206", "Each risk shall be assigned a level using a predefined scheme that considers how likely the scenario is "
                "and how severe the safety consequences would be.", "Cumple", "IS.I.OR.205"),
    ("SEC-207", "The risk analysis shall be revisited when systems, interfaces or threat knowledge change, and to take "
                "into account lessons learned from past incidents.", "Cumple", "IS.I.OR.205"),
    ("SEC-208", "The organisation shall list the elements that could be exposed, including its activities, facilities, "
                "equipment, systems and data.", "Cumple", "IS.I.OR.205"),
    ("SEC-209", "Staff shall be able to report security events through an internal channel; reported events shall be "
                "gathered and assessed.", "Cumple", "IS.I.OR.215"),
    ("SEC-210", "Subcontractors are encouraged to mention cyber problems when convenient.", "No cumple", "IS.I.OR.215"),
    ("SEC-211", "Security monitoring tools shall be deployed.", "No cumple", "IS.I.OR.220"),
    ("SEC-212", "Predefined response teams and resources shall be activated to contain the spread of an incident.",
     "Cumple", "IS.I.OR.220"),
    ("SEC-213", "Following an incident, the root cause shall be eliminated and systems restored to a secure state within "
                "a defined recovery time.", "Cumple", "IS.I.OR.220"),
    ("SEC-214", "When the authority raises a finding, the organisation shall identify the root cause and propose a "
                "corrective action plan within the period agreed with the authority.", "Cumple", "IS.I.OR.225"),
    ("SEC-215", "Findings from the authority shall be addressed.", "No cumple", "IS.I.OR.225"),
    ("SEC-216", "Information security management records shall be archived for at least five years.", "Cumple", "IS.I.OR.245"),
    ("SEC-217", "Logs of the security management system shall be retained for 24 months.", "No cumple", "IS.I.OR.245"),
    ("SEC-218", "Changes to the ISMS that are not covered by the approved change procedure shall be approved by the "
                "competent authority before they are implemented.", "Cumple", "IS.I.OR.255"),
    ("SEC-219", "Major ISMS changes shall be communicated to the authority after implementation.", "No cumple", "IS.I.OR.255"),
    ("SEC-220", "Security performance indicators shall be reviewed from time to time.", "No cumple", "IS.I.OR.260"),
    ("SEC-221", "Employees shall be entitled to 23 days of annual leave.", "No aplica", ""),
    ("SEC-222", "Personnel involved in information security shall receive training and their competence shall be "
                "assessed regularly.", "Cumple", "IS.I.OR.240"),
    ("SEC-223", "Results of the risk assessment shall be communicated to affected staff and to organisations with which "
                "interfaces exist.", "Cumple", "IS.I.OR.210"),
]

CONTRADICCIONES = [
    ("SEC-201", "SEC-202", "plazo de notificación a la autoridad", "72 horas vs una semana"),
    ("SEC-216", "SEC-217", "retención de registros", "5 años vs 24 meses"),
]


def main():
    SALIDA.mkdir(exist_ok=True)
    lineas = ["# Cyber requirements (blind test 2)", "", "## Requirements", ""]
    lineas += [f"**{r[0]}** {r[1]}\n" for r in REQUISITOS]
    (SALIDA / "documento_requisitos.md").write_text("\n".join(lineas), encoding="utf-8")
    pd.DataFrame([(r[0], r[2], r[3]) for r in REQUISITOS],
                 columns=["req_id", "veredicto_gold", "clausula_gold"]).to_csv(SALIDA / "gold.csv", index=False)
    pd.DataFrame(CONTRADICCIONES, columns=["req_a", "req_b", "parametro", "detalle"]).to_csv(
        SALIDA / "gold_contradicciones.csv", index=False)
    print(f"{len(REQUISITOS)} requisitos → {SALIDA}")


if __name__ == "__main__":
    main()
