"""
Copiloto LLM (opcional). Reescribe la explicación de una UM-día en lenguaje de negocio.

Reglas:
  - El LLM solo recibe datos ya calculados (hechos()).
  - Salida en JSON validado con Pydantic; si no valida, se reintenta.
  - Anti-invención: cualquier número del texto debe estar en los datos de entrada; si no, se rechaza.

Proveedor configurable en .env: LLM_PROVEEDOR = azure | openai | ninguno
"""
import json
import math
import re

from pydantic import BaseModel, Field, ValidationError

import config


class Explicacion(BaseModel):
    resumen: str = Field(description="1-2 frases para el técnico de validación")
    causa_probable: str
    recomendacion: str


PROMPT = """Eres un técnico experto en validación de medidas de gas. Redacta en español una explicación breve
de por qué esta Unidad de Medida tiene este nivel de revisión. Usa SOLO las cifras de los DATOS (puedes
redondearlas, no calcules ni inventes cifras nuevas). Responde solo con JSON con las claves:
resumen, causa_probable, recomendacion.

DATOS:
{datos}"""


def hechos(r) -> dict:
    claves = ["um_id", "fecha", "nivel", "tipo_um", "tipo_consumo", "ramal", "causa_probable", "explicacion",
              "recomendacion", "dif_orion", "umbral_ad_dif_orion", "dif_his_signo", "umbral_ad_dif_his",
              "dif_pcs", "umbral_ad_dif_pcs", "ramal_dif_his"]
    salida = {}
    for k in claves:
        v = r[k] if k in r else None
        if isinstance(v, float) and math.isnan(v):
            v = None
        salida[k] = str(v)[:10] if k == "fecha" else v
    return salida


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
    salida = set()
    for n in re.findall(r"\d+(?:[.,]\d+)*", texto):
        limpio = n.replace(".", "").replace(",", ".") if re.search(r"\.\d{3}", n) else n.replace(",", ".")
        try:
            x = abs(float(limpio))
            salida |= {round(x, 1), round(x * 100, 1)}  # admite 0.023 escrito como 2,3 %
        except ValueError:
            pass
    return salida


def _sin_inventos(exp: Explicacion, datos: dict) -> bool:
    permitidos = _numeros(json.dumps(datos, ensure_ascii=False, default=str))
    usados = {round(abs(float(n.replace(",", "."))), 1)
              for n in re.findall(r"\d+(?:,\d+)?", " ".join([exp.resumen, exp.causa_probable, exp.recomendacion]))
              if n}
    return all(any(abs(u - p) <= max(1, 0.05 * p) for p in permitidos) for u in usados)


def redactar(datos: dict, intentos: int = 3) -> tuple[Explicacion | None, str]:
    if not disponible():
        return None, "LLM no configurado (LLM_PROVEEDOR en .env)"
    cliente, modelo = _cliente()
    mensaje = PROMPT.format(datos=json.dumps(datos, ensure_ascii=False, default=str, indent=2))
    ultimo = ""
    for _ in range(intentos):
        try:
            r = cliente.chat.completions.create(model=modelo, temperature=0.2, response_format={"type": "json_object"},
                                                messages=[{"role": "user", "content": mensaje}])
            exp = Explicacion.model_validate_json(r.choices[0].message.content)
            if not _sin_inventos(exp, datos):
                ultimo = "el LLM incluyó cifras que no estaban en los datos"
                mensaje += "\n\nIMPORTANTE: tu respuesta anterior contenía cifras inventadas. Usa solo las de DATOS."
                continue
            return exp, "ok"
        except ValidationError as e:
            ultimo = f"JSON no válido: {e.errors()[0]['msg']}"
        except Exception as e:
            return None, f"error llamando al LLM: {e}"
    return None, ultimo
