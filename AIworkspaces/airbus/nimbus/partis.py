"""
Plazos que fija directamente Part-IS (Reg. de Ejecución (UE) 2023/203, anexo II) y que el estándar corporativo
NO reproduce a propósito ("el fijado por el Reglamento").

Cada plazo se valida contra el TEXTO OFICIAL en español (normativa/clausulas_es.json): si la frase no aparece
literalmente en el reglamento, no se usa. Así cada hallazgo puede citar la frase exacta del reglamento.
"""
import json
import re
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "normativa" / "clausulas_es.json"

# nombre (como lo llaman los documentos internos), cláusula, frase del reglamento (regex), sentido, horas
PLAZOS = [
    ("Notificación a la autoridad competente", "IS.I.OR.230", r"como máximo, en las 72 horas", "max", 72),
    ("Conservación de los registros del ISMS", "IS.I.OR.245", r"se conservarán al menos durante un período de cinco años", "min", 5 * 8760),
    ("Conservación de registros de cualificación del personal", "IS.I.OR.245",
     r"al menos hasta tres años después de que la persona haya abandonado la organización", "min", 3 * 8760),
]


def plazos() -> list[dict]:
    """Plazos con su cita literal comprobada en el texto oficial."""
    try:
        cl = json.loads(RUTA.read_text(encoding="utf-8"))["clausulas"]
    except Exception:
        return []
    salida = []
    for nombre, clausula, patron, sentido, horas in PLAZOS:
        texto = re.sub(r"\s+", " ", cl.get(clausula, {}).get("texto", ""))
        m = re.search(r"[^.;]*" + patron + r"[^.;]*", texto)
        if m:
            salida.append({"nombre": nombre, "clausula": clausula, "sentido": sentido, "horas": horas,
                           "cita": m.group(0).strip()})
    return salida
