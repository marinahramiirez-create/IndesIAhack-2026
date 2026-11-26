"""
Cliente LLM (endpoint Anthropic de la plataforma IndesIA en Azure). Claves solo en .env.

- Temperatura 0 y salida JSON validada con Pydantic (guía §9.1); si no valida, se reintenta.
- Reintentos con espera ante límites de ritmo (guía §11: plataformas compartidas).
- El bloque de referencias (Part-IS + estándar + lista maestra) se marca para caché: se envía igual en cada
  documento y el proveedor lo reutiliza → menos coste y menos latencia (guía §9.2).
"""
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
MODELO_AUDITOR = os.getenv("MODELO_AUDITOR", "claude-sonnet-5-5")
MODELO_RAPIDO = os.getenv("MODELO_RAPIDO", "claude-haiku-5-5")
CACHE = Path(__file__).resolve().parent.parent / "cache" / "llm"

_cli = None


def cliente() -> Anthropic:
    global _cli
    if _cli is None:
        clave = os.getenv("AZURE_API_KEY", "").strip()
        if not clave:
            raise RuntimeError("Falta AZURE_API_KEY en .env")
        _cli = Anthropic(api_key=clave, base_url=os.getenv("ANTHROPIC_BASE_URL"), max_retries=4, timeout=600)
    return _cli


def _json(texto: str):
    """Extrae el primer objeto JSON de la respuesta (admite ```json ... ```)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto, re.S) or re.search(r"(\{.*\})", texto, re.S)
    if not m:
        raise ValueError("la respuesta no contiene JSON")
    return json.loads(m.group(1))


def pedir_json(sistema: str, usuario: str | list, esquema, modelo: str = MODELO_AUDITOR,
               max_tokens: int = 16000, intentos: int = 3):
    """Llama al modelo y valida la respuesta con el esquema Pydantic. Devuelve (objeto, uso)."""
    contenido = usuario if isinstance(usuario, list) else [{"type": "text", "text": usuario}]
    # Reproducibilidad: misma entrada → misma salida (respuesta guardada en disco). El SDK actual ya no admite
    # 'temperature', así que la determinación se consigue con esta caché.
    huella = hashlib.sha256(json.dumps([modelo, sistema, contenido], ensure_ascii=False, sort_keys=True)
                            .encode()).hexdigest()[:24]
    fichero = CACHE / f"{huella}.json"
    if fichero.exists():
        return esquema.model_validate(json.loads(fichero.read_text(encoding="utf-8"))), None
    ultimo_error = None
    for i in range(intentos):
        try:
            # streaming: las respuestas largas tardan minutos y sin flujo la conexión se corta por inactividad
            with cliente().messages.stream(
                    model=modelo, max_tokens=max_tokens,
                    system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": contenido}]) as s:
                r = s.get_final_message()
            texto = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            datos = _json(texto)
            obj = esquema.model_validate(datos)
            CACHE.mkdir(parents=True, exist_ok=True)
            fichero.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
            return obj, r.usage
        except Exception as e:     # JSON roto o error transitorio → reintento acotado
            ultimo_error = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"El LLM no devolvió una respuesta válida: {ultimo_error!r}")


def imagen(png: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(png).decode()}}
