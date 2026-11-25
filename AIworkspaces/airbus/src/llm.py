"""
LLM (opcional). Proveedor en .env: LLM_PROVEEDOR = azure | openai | ninguno

Qué hace el LLM y qué NO hace (regla del proyecto: el LLM interpreta, el código decide):
  1. elegir_obligacion:  de las obligaciones candidatas que trae el RAG, elige la que aplica (reordenación).
                         Solo puede devolver un ID de la lista → no puede inventar cláusulas.
  2. evaluar_elementos:  para cada elemento que exige la obligación, dice si el requisito lo cubre y COPIA la frase
                         literal del requisito que lo demuestra. Si la frase no está en el requisito → no cuenta.
                         Se pregunta n veces (autoconsistencia): si los juicios no coinciden → "dudoso" → Revisar.
  3. El veredicto lo calcula el código (auditor.juicio_reglas) con esos elementos + límites numéricos + vaguedad.

Todas las salidas son JSON validado con Pydantic; si no valida, se reintenta.
Para probar sin claves: asignar CLIENTE_FALSO = (cliente, modelo) con un objeto que imite al de OpenAI.
"""
import json
import re

from pydantic import BaseModel, Field, ValidationError

import config

CLIENTE_FALSO = None   # solo para tests


# ---------------------------------------------------------------- esquemas de salida
class Eleccion(BaseModel):
    obligacion_id: str = Field(description="ID de una de las candidatas, o 'ninguna'")
    motivo: str = ""


class Elemento(BaseModel):
    nombre: str
    presente: bool
    cita_requisito: str = Field(default="", description="frase copiada literalmente del requisito; vacío si no está")


class Evaluacion(BaseModel):
    elementos: list[Elemento]


PROMPT_ELEGIR = """You are an EASA Part-IS compliance auditor. Which candidate obligation does this REQUIREMENT address?
Answer with the ID of exactly one candidate, or "ninguna" if none applies. Use only the candidates below.
Return JSON: {{"obligacion_id": "...", "motivo": "short reason in Spanish"}}

REQUIREMENT {req_id}: {texto}

CANDIDATES:
{candidatas}"""

PROMPT_ELEMENTOS = """You are an EASA Part-IS compliance auditor. The OBLIGATION below requires several elements.
For EACH element, decide whether the REQUIREMENT explicitly covers it (synonyms count: e.g. "audit trails" are records,
"every six months" is a predefined calendar, "prior approval" means before the change). Do not assume what is not written.
If present, copy in "cita_requisito" the exact words from the REQUIREMENT that show it (verbatim substring).
Return JSON: {{"elementos": [{{"nombre": "<element name as given>", "presente": true|false, "cita_requisito": "..."}}]}}

OBLIGATION {ob_id} ({clausula} {apartado}): {texto_norma}
ELEMENTS: {elementos}

REQUIREMENT {req_id}: {texto}"""


def disponible() -> bool:
    if CLIENTE_FALSO:
        return True
    if config.LLM_PROVEEDOR == "azure":
        return bool(config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_KEY and config.AZURE_OPENAI_DEPLOYMENT)
    if config.LLM_PROVEEDOR == "openai":
        return bool(config.OPENAI_API_KEY)
    return False


def _cliente():
    if CLIENTE_FALSO:
        return CLIENTE_FALSO
    if config.LLM_PROVEEDOR == "azure":
        from openai import AzureOpenAI
        return AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                           api_version=config.AZURE_OPENAI_API_VERSION), config.AZURE_OPENAI_DEPLOYMENT
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY), config.OPENAI_MODEL


def _json(prompt: str, esquema: type[BaseModel], temperatura: float = 0.0, intentos: int = 2):
    """Llama al LLM pidiendo JSON y lo valida con Pydantic. Devuelve (objeto | None, error)."""
    cliente, modelo = _cliente()
    error = ""
    for _ in range(intentos):
        try:
            r = cliente.chat.completions.create(model=modelo, temperature=temperatura,
                                                response_format={"type": "json_object"},
                                                messages=[{"role": "user", "content": prompt}])
            return esquema.model_validate_json(r.choices[0].message.content), ""
        except ValidationError as e:
            error = f"JSON no válido: {e.errors()[0]['msg']}"
        except Exception as e:           # red, credenciales, cuota...
            return None, f"error llamando al LLM: {e}"
    return None, error


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def cita_literal(cita: str, texto: str) -> bool:
    """La cita debe aparecer en el texto (ignorando mayúsculas y puntuación). Se admiten '...' entre trozos."""
    trozos = [_norm(t) for t in re.split(r"\.\.\.|…", cita) if len(_norm(t)) >= 3]
    return bool(trozos) and all(t in _norm(texto) for t in trozos)


# ---------------------------------------------------------------- 1. reordenación
def elegir_obligacion(req: dict, candidatas: list[dict]) -> tuple[str | None, str]:
    lista = "\n".join(f"- {c['id']} | {c['clausula']} {c['apartado']} | {c['tema']}: {c['texto_norma'][:300]}"
                      for c in candidatas)
    r, error = _json(PROMPT_ELEGIR.format(req_id=req["req_id"], texto=req["texto"], candidatas=lista), Eleccion)
    if r is None:
        return None, error
    validos = {c["id"] for c in candidatas}
    if r.obligacion_id == "ninguna":
        return "ninguna", r.motivo
    return (r.obligacion_id, r.motivo) if r.obligacion_id in validos else (None, "ID fuera de las candidatas: ignorado")


# ---------------------------------------------------------------- 2. elementos con evidencia
def evaluar_elementos(req: dict, ob: dict, n: int = 3) -> tuple[dict | None, list[str], str]:
    """
    Devuelve ({nombre: {"presente", "cita", "dudoso"}}, resumen de votos, error).
    Un elemento cuenta como presente solo si la mayoría lo ve Y su cita está literalmente en el requisito.
    """
    nombres = [e["nombre"] for e in ob.get("elementos", [])]
    if not nombres:
        return {}, [], ""
    prompt = PROMPT_ELEMENTOS.format(ob_id=ob["id"], clausula=ob["clausula"], apartado=ob["apartado"],
                                     texto_norma=ob["texto_norma"], elementos=json.dumps(nombres, ensure_ascii=False),
                                     req_id=req["req_id"], texto=req["texto"])
    juicios, error = [], ""
    for i in range(n):
        r, error = _json(prompt, Evaluacion, temperatura=0.0 if i == 0 else 0.7)
        if r is not None:
            juicios.append({e.nombre: e for e in r.elementos})
    if not juicios:
        return None, [], error

    salida, votos = {}, []
    for nombre in nombres:
        si, citas = 0, []
        for j in juicios:
            e = j.get(nombre)
            # verificador: "presente" sin cita literal en el requisito no cuenta
            if e and e.presente and cita_literal(e.cita_requisito, req["texto"]):
                si += 1
                citas.append(e.cita_requisito)
        presente = si * 2 > len(juicios)
        salida[nombre] = {"presente": presente, "cita": citas[0] if citas else "",
                          "dudoso": 0 < si < len(juicios)}
        votos.append(f"{nombre}: {si}/{len(juicios)}")
    return salida, votos, ""


# ---------------------------------------------------------------- otros usos
def reformular(texto: str) -> str | None:
    """Bucle de reflexión: el LLM reescribe la consulta con el vocabulario de Part-IS."""
    if not disponible():
        return None
    try:
        cliente, modelo = _cliente()
        r = cliente.chat.completions.create(model=modelo, temperature=0, messages=[{"role": "user", "content":
            "Rewrite this requirement as a search query using EASA Part-IS vocabulary (e.g. recovery, safe state, "
            "competent authority, records retention, risk assessment). Return only the query.\n\n" + texto}])
        return r.choices[0].message.content.strip()
    except Exception:
        return None
