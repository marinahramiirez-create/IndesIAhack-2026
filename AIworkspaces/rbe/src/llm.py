"""
Copiloto LLM (opcional). Reescribe la explicación en lenguaje de negocio.

Reglas que se cumplen aquí:
  - El LLM solo recibe datos ya calculados (explicar.hechos).
  - La salida es JSON validado con Pydantic; si no valida, se reintenta.
  - Comprobación anti-invención: cualquier número del texto debe estar en los datos de entrada.
    Si el LLM se inventa una cifra, se rechaza y se usa la plantilla.

Proveedor configurable en .env: LLM_PROVEEDOR = azure | openai | ninguno
"""
import json
import re

from pydantic import BaseModel, Field, ValidationError

import config


class Explicacion(BaseModel):
    resumen: str = Field(description="1-2 frases para un director de operaciones")
    causa_probable: str = Field(description="hipótesis basada solo en los datos")
    recomendacion: str = Field(description="acción concreta")


PROMPT = """Eres un analista de operaciones de restaurantes. Redacta en español una explicación breve
de esta alerta para una persona no técnica. Usa SOLO las cifras de los DATOS (puedes redondearlas,
pero no calcules ni inventes cifras nuevas). Responde solo con JSON con las claves:
resumen, causa_probable, recomendacion.

DATOS:
{datos}"""


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


def _numeros(texto: str) -> set[float]:
    encontrados = re.findall(r"\d+(?:[.,]\d+)*", texto)
    salida = set()
    for n in encontrados:
        limpio = n.replace(".", "").replace(",", ".") if re.search(r"\.\d{3}", n) else n.replace(",", ".")
        try:
            salida.add(round(abs(float(limpio))))
        except ValueError:
            pass
    return salida


def _sin_inventos(exp: Explicacion, datos: dict) -> bool:
    permitidos = _numeros(json.dumps(datos, ensure_ascii=False, default=str))
    usados = _numeros(" ".join([exp.resumen, exp.causa_probable, exp.recomendacion]))
    # se permite redondear: un número usado vale si está a ±1 de alguno permitido
    return all(any(abs(u - p) <= 1 for p in permitidos) for u in usados)


def redactar(datos: dict, intentos: int = 3) -> tuple[Explicacion | None, str]:
    """Devuelve (explicación, estado). Si falla, (None, motivo) y la app usa la plantilla."""
    if not disponible():
        return None, "LLM no configurado (LLM_PROVEEDOR en .env)"
    cliente, modelo = _cliente()
    mensaje = PROMPT.format(datos=json.dumps(datos, ensure_ascii=False, default=str, indent=2))
    ultimo_error = ""
    for _ in range(intentos):
        try:
            r = cliente.chat.completions.create(
                model=modelo, temperature=0.2, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": mensaje}],
            )
            exp = Explicacion.model_validate_json(r.choices[0].message.content)
            if not _sin_inventos(exp, datos):
                ultimo_error = "el LLM incluyó cifras que no estaban en los datos"
                mensaje += "\n\nIMPORTANTE: tu respuesta anterior contenía cifras inventadas. Usa solo las de DATOS."
                continue
            return exp, "ok"
        except ValidationError as e:
            ultimo_error = f"JSON no válido: {e.errors()[0]['msg']}"
        except Exception as e:  # red, credenciales...
            return None, f"error llamando al LLM: {e}"
    return None, ultimo_error
