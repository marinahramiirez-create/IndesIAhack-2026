"""
Juez LLM (opcional). Proveedor en .env: LLM_PROVEEDOR = azure | openai | ninguno

Reglas que se cumplen aquí:
  - El LLM solo juzga con la evidencia recuperada (obligaciones + texto de la norma); no calcula plazos.
  - Salida en JSON validado con Pydantic; si no valida, se reintenta.
  - Autoconsistencia: se le pregunta n veces (temperatura > 0) y se comparan los veredictos.
  - Debe citar literalmente la norma (cita_norma); auditor.py comprueba que la cita existe.
"""
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

import config


class Juicio(BaseModel):
    veredicto: Literal["Cumple", "No cumple", "Revisar"]
    clausula: str = Field(description="ID exacto de la cláusula, p. ej. IS.I.OR.245")
    apartado: str = Field(default="", description="p. ej. (a)(4)")
    cita_norma: str = Field(description="frase copiada LITERALMENTE del texto de la norma que respalda el veredicto")
    fragmento_requisito: str = Field(default="", description="trozo literal del requisito que incumple (vacío si cumple)")
    justificacion: str = Field(description="1-2 frases en español")
    confianza: float = Field(ge=0, le=1)


PROMPT = """Eres auditor de ciberseguridad aeronáutica (EASA Part-IS). Decide si el REQUISITO cumple la
obligación aplicable de la NORMA. Usa SOLO el texto de la NORMA que te doy; no uses conocimiento externo.

Criterios:
- "Cumple": el requisito recoge todos los elementos que exige la obligación, con verbo obligatorio (shall).
- "No cumple": falta un elemento exigido, contradice la norma o fija un valor peor que el límite.
- "Revisar": la redacción es ambigua o la norma recuperada no permite decidir.

Responde SOLO con JSON con las claves: veredicto, clausula, apartado, cita_norma, fragmento_requisito,
justificacion, confianza. "cita_norma" debe ser una frase copiada literalmente de la NORMA.

REQUISITO {req_id}: {texto}

OBLIGACIONES CANDIDATAS:
{obligaciones}

NORMA (fragmentos recuperados):
{fragmentos}"""


def disponible() -> bool:
    if config.LLM_PROVEEDOR == "azure":
        return bool(config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_KEY and config.AZURE_OPENAI_DEPLOYMENT)
    if config.LLM_PROVEEDOR == "openai":
        return bool(config.OPENAI_API_KEY)
    return False


def _cliente():
    if config.LLM_PROVEEDOR == "azure":
        from openai import AzureOpenAI
        return AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                           api_version=config.AZURE_OPENAI_API_VERSION), config.AZURE_OPENAI_DEPLOYMENT
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY), config.OPENAI_MODEL


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def cita_literal(cita: str, texto_norma: str) -> bool:
    """La cita debe aparecer en la norma (ignorando mayúsculas y puntuación). Se admiten '...' entre trozos."""
    trozos = [_norm(t) for t in re.split(r"\.\.\.|…", cita) if len(_norm(t)) > 15]
    return bool(trozos) and all(t in _norm(texto_norma) for t in trozos)


def juzgar(req: dict, obligaciones: list[dict], fragmentos: list[dict], n: int = 3) -> tuple[list[Juicio], str]:
    """n juicios independientes. Devuelve (juicios válidos, último error)."""
    if not disponible():
        return [], "LLM no configurado"
    cliente, modelo = _cliente()
    mensaje = PROMPT.format(
        req_id=req["req_id"], texto=req["texto"],
        obligaciones="\n".join(f"- {o['clausula']} {o['apartado']} · {o['tema']}: {o['texto_norma']}" for o in obligaciones),
        fragmentos="\n".join(f"[{f['clausula']} {f['apartado']} · {f['tipo']}] {f['texto'][:1200]}" for f in fragmentos),
    )
    juicios, error = [], ""
    for _ in range(n):
        for _intento in range(2):   # reintento si el JSON no valida
            try:
                r = cliente.chat.completions.create(
                    model=modelo, temperature=0.7, response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": mensaje}])
                juicios.append(Juicio.model_validate_json(r.choices[0].message.content))
                break
            except ValidationError as e:
                error = f"JSON no válido: {e.errors()[0]['msg']}"
            except Exception as e:      # red, credenciales, cuota...
                return juicios, f"error llamando al LLM: {e}"
    return juicios, error


def reformular(texto: str) -> str | None:
    """Bucle de reflexión: el LLM reescribe la consulta con el vocabulario de Part-IS."""
    if not disponible():
        return None
    cliente, modelo = _cliente()
    try:
        r = cliente.chat.completions.create(model=modelo, temperature=0, messages=[{"role": "user", "content":
            "Rewrite this requirement as a search query using EASA Part-IS vocabulary (e.g. recovery, safe state, "
            "competent authority, records retention, risk assessment). Return only the query.\n\n" + texto}])
        return r.choices[0].message.content.strip()
    except Exception:
        return None


def redactar_informe(resumen: dict) -> str | None:
    """Resumen ejecutivo del informe, solo con cifras ya calculadas."""
    if not disponible():
        return None
    cliente, modelo = _cliente()
    try:
        r = cliente.chat.completions.create(model=modelo, temperature=0.2, messages=[{"role": "user", "content":
            "Redacta en español un resumen ejecutivo de 4 frases de esta auditoría. Usa SOLO estas cifras, "
            "no calcules ni inventes otras:\n" + json.dumps(resumen, ensure_ascii=False)}])
        return r.choices[0].message.content.strip()
    except Exception:
        return None
