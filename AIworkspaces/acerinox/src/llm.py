"""
LLM y voz (opcionales). Proveedor en .env: LLM_PROVEEDOR = azure | openai | ninguno

Reglas que se cumplen aquí:
  - completar_ficha: el LLM solo rellena huecos que las reglas no entendieron; la salida es JSON validado
    con Pydantic y CADA valor se comprueba contra el catálogo (grado/acabado/formato inventado → se descarta).
  - redactar: reescribe la respuesta en lenguaje natural; si menciona un bulto que no está en las propuestas
    o un grado que no existe, se rechaza y se usa la respuesta de plantilla.
  - transcribir: voz → texto con Whisper (despliegue de Azure OpenAI o API de OpenAI).
"""
import io
import json
import re

from pydantic import BaseModel, ValidationError

import config
from src import catalogo


class FichaLLM(BaseModel):
    grados: list[str] = []
    acabado: str | None = None
    espesor_mm: float | None = None
    formato: str | None = None
    ancho_mm: float | None = None
    largo_mm: float | None = None
    cantidad_kg: float | None = None
    piezas: int | None = None


PROMPT_FICHA = """Eres un técnico comercial de acero inoxidable. Convierte la petición del cliente en una ficha técnica.
Usa SOLO estos valores (si no está claro, deja null; NO inventes):
- grados: {grados}
- acabado: {acabados}
- formato: {formatos}
- espesor_mm: uno de {espesores}
Diccionario del catálogo (evidencia):
{catalogo}

Petición: "{texto}"
Responde SOLO con JSON con las claves: grados (lista), acabado, espesor_mm, formato, ancho_mm, largo_mm, cantidad_kg, piezas."""


def disponible() -> bool:
    if config.LLM_PROVEEDOR == "azure":
        return bool(config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_KEY and config.AZURE_OPENAI_DEPLOYMENT)
    if config.LLM_PROVEEDOR == "openai":
        return bool(config.OPENAI_API_KEY)
    return False


def voz_disponible() -> bool:
    if config.LLM_PROVEEDOR == "azure":
        return bool(config.AZURE_OPENAI_KEY and config.AZURE_OPENAI_WHISPER)
    return config.LLM_PROVEEDOR == "openai" and bool(config.OPENAI_API_KEY)


def _cliente():
    if config.LLM_PROVEEDOR == "azure":
        from openai import AzureOpenAI
        return AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                           api_version=config.AZURE_OPENAI_API_VERSION), config.AZURE_OPENAI_DEPLOYMENT
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY), config.OPENAI_MODEL


def completar_ficha(texto: str, ficha):
    """Rellena SOLO los campos vacíos de la ficha. Valores fuera de catálogo se descartan."""
    v = catalogo.valores_validos()
    resumen = " | ".join(f"{s['titulo']}: {s['texto'][:160]}" for s in catalogo.secciones()[:14])
    mensaje = PROMPT_FICHA.format(grados=v["grado"], acabados=v["acabado"], formatos=v["formato"],
                                  espesores=v["espesores"], catalogo=resumen, texto=texto)
    try:
        cliente, modelo = _cliente()
        for _ in range(2):
            r = cliente.chat.completions.create(model=modelo, temperature=0, response_format={"type": "json_object"},
                                                messages=[{"role": "user", "content": mensaje}])
            try:
                p = FichaLLM.model_validate_json(r.choices[0].message.content)
                break
            except ValidationError:
                continue
        else:
            return ficha
    except Exception:
        return ficha

    f = ficha.model_copy(deep=True)
    grados_ok = [g for g in p.grados if g in v["grado"]]
    if not f.grados and not f.grado_indiferente and grados_ok:
        f.grados = grados_ok
        f.evidencias.append({"campo": "grado", "valor": " o ".join(grados_ok), "texto": texto, "cita": "interpretado por IA"})
    for campo, validos in [("acabado", v["acabado"]), ("formato", v["formato"])]:
        valor = getattr(p, campo)
        if getattr(f, campo) is None and valor in validos:
            setattr(f, campo, valor)
            f.evidencias.append({"campo": campo, "valor": valor, "texto": texto, "cita": "interpretado por IA"})
    for campo in ["espesor_mm", "ancho_mm", "largo_mm", "cantidad_kg", "piezas"]:
        valor = getattr(p, campo)
        # anti-invención: el número tiene que aparecer en lo que dijo el cliente
        if getattr(f, campo) is None and valor is not None and _numero_en_texto(valor, texto):
            if campo == "espesor_mm" and valor not in v["espesores"]:
                continue
            setattr(f, campo, valor)
            f.evidencias.append({"campo": campo.replace("_mm", ""), "valor": valor, "texto": texto, "cita": "interpretado por IA"})
    return f


def _numero_en_texto(valor: float, texto: str) -> bool:
    from src.interprete import NUM_PALABRA
    numeros = {float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", texto)}
    numeros |= {float(NUM_PALABRA[w]) for w in re.findall(r"\w+", texto.lower()) if w in NUM_PALABRA}
    return any(abs(valor - n) < 1e-6 or abs(valor - n * 1000) < 1e-6 for n in numeros)


def redactar(respuesta_base: str, ids_permitidos: list[str]) -> str:
    """Versión más natural de la respuesta. Si menciona IDs o grados no permitidos → se usa la base."""
    if not disponible():
        return respuesta_base
    try:
        cliente, modelo = _cliente()
        r = cliente.chat.completions.create(model=modelo, temperature=0.3, messages=[{"role": "user", "content":
            "Reescribe esta respuesta de un asistente comercial de acero inoxidable para que suene natural y breve, "
            "en español. NO añadas bultos, grados, cifras ni propiedades que no estén en el texto:\n\n" + respuesta_base}])
        nuevo = r.choices[0].message.content.strip()
    except Exception:
        return respuesta_base
    ids = set(re.findall(r"B-\d+", nuevo))
    if not ids <= set(ids_permitidos):
        return respuesta_base
    numeros_base = set(re.findall(r"\d+(?:[.,]\d+)?", respuesta_base))
    if not set(re.findall(r"\d+(?:[.,]\d+)?", nuevo)) <= numeros_base:
        return respuesta_base
    return nuevo


def transcribir(audio: bytes, nombre: str = "audio.wav") -> str | None:
    if not voz_disponible():
        return None
    try:
        if config.LLM_PROVEEDOR == "azure":
            from openai import AzureOpenAI
            cli = AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                              api_version=config.AZURE_OPENAI_API_VERSION)
            modelo = config.AZURE_OPENAI_WHISPER
        else:
            from openai import OpenAI
            cli, modelo = OpenAI(api_key=config.OPENAI_API_KEY), "whisper-1"
        archivo = io.BytesIO(audio)
        archivo.name = nombre
        return cli.audio.transcriptions.create(model=modelo, file=archivo, language="es").text
    except Exception as e:
        return f"[error de transcripción: {e}]"
