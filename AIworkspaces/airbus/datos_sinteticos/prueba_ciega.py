"""
Prueba ciega: requisitos redactados con OTRAS palabras que el documento principal, escritos sin mirar
las reglas del auditor y sin ajustarlas después. Sirve para medir cuánto generaliza el juez por reglas
(el F1 del documento principal está inflado porque reglas y documento se hicieron a la vez).

Ejecutar desde airbus/:
    python datos_sinteticos/prueba_ciega.py
    (en PowerShell)  $env:DIR_DATOS="datos_sinteticos/salida_ciega"; python -m src.pipeline; Remove-Item Env:DIR_DATOS
"""
from pathlib import Path

import pandas as pd

SALIDA = Path(__file__).resolve().parent / "salida_ciega"

REQUISITOS = [
    ("SEC-101", "Cyber incidents with a possible safety impact must be communicated to the national aviation authority within three days.",
     "No cumple", "IS.I.OR.230"),
    ("SEC-102", "The company shall inform the competent authority without delay and send the full incident report within 48 hours.",
     "Cumple", "IS.I.OR.230"),
    ("SEC-103", "Audit trails of the maintenance IT systems shall be kept for one year.",
     "No cumple", "IS.I.OR.245"),
    ("SEC-104", "Information security records, including risk registers and incident reports, shall be retained for ten years with integrity protection.",
     "Cumple", "IS.I.OR.245"),
    ("SEC-105", "A CISO shall be nominated who reports directly to the accountable manager, with a designated deputy for lengthy absences.",
     "Cumple", "IS.I.OR.240"),
    ("SEC-106", "Cyber risks shall be rated by the security team.",
     "No cumple", "IS.I.OR.205"),
    ("SEC-107", "Suppliers handling ISMS tasks shall be supervised by the organisation, shall comply with Part-IS and shall grant access to the competent authority on request.",
     "Cumple", "IS.I.OR.235"),
    ("SEC-108", "The ISMS performance shall be measured with KPIs every six months and after each security incident.",
     "Cumple", "IS.I.OR.260"),
    ("SEC-109", "Mitigations shall be applied to unacceptable cyber risks.",
     "No cumple", "IS.I.OR.210"),
    ("SEC-110", "Intrusion detection shall compare network behaviour against a defined baseline and raise alarms to the security operations centre.",
     "Cumple", "IS.I.OR.220"),
    ("SEC-111", "After a cyber attack, systems should be brought back online.",
     "No cumple", "IS.I.OR.220"),
    ("SEC-112", "Modifications of the ISMS outside the approved procedure shall obtain prior approval of the competent authority.",
     "Cumple", "IS.I.OR.255"),
    ("SEC-113", "The cafeteria menu shall be published every Monday.",
     "No aplica", ""),
    ("SEC-114", "Audit trails of the maintenance IT systems shall be kept for seven years.",
     "Cumple", "IS.I.OR.245"),
]


def main():
    SALIDA.mkdir(exist_ok=True)
    lineas = ["# Cyber requirements (blind test)", "", "## Requirements", ""]
    lineas += [f"**{r[0]}** {r[1]}\n" for r in REQUISITOS]
    (SALIDA / "documento_requisitos.md").write_text("\n".join(lineas), encoding="utf-8")
    pd.DataFrame([(r[0], r[2], r[3]) for r in REQUISITOS],
                 columns=["req_id", "veredicto_gold", "clausula_gold"]).to_csv(SALIDA / "gold.csv", index=False)
    pd.DataFrame([("SEC-103", "SEC-114", "retención de registros", "1 año vs 7 años")],
                 columns=["req_a", "req_b", "parametro", "detalle"]).to_csv(SALIDA / "gold_contradicciones.csv", index=False)
    print(f"{len(REQUISITOS)} requisitos → {SALIDA}")


if __name__ == "__main__":
    main()
