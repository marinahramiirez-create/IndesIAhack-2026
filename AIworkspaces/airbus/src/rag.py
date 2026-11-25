"""
Recuperación (RAG) sobre la normativa.

Dos índices:
  - obligaciones: obligaciones atómicas (normativa/obligaciones.json), cada una ligada a cláusula + apartado.
  - fragmentos:   texto de la normativa troceado por cláusula y apartado (IR, AMC y GM), para dar contexto
                  al LLM y enseñar la evidencia en la interfaz.

Búsqueda: BM25 (palabras clave). Si hay modelo de embeddings en Azure (AZURE_OPENAI_EMBEDDINGS en .env),
se combina con similitud de vectores → búsqueda híbrida. El día del reto se puede sustituir por
Azure AI Search sin tocar el resto: basta con que buscar_* devuelva la misma estructura.
"""
import json
import os
import re
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

import config
from src import normativa

PARADAS = set("""a an the and or of to in on for by with as at be is are shall should may must will its it this that
those these such any all each from into than then which who whom whose within where when not no""".split())


def tokens(texto: str) -> list[str]:
    salida = []
    for t in re.findall(r"[a-záéíóúñ0-9]+", texto.lower()):
        if t in PARADAS or len(t) < 2:
            continue
        for suf in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                t = t[: -len(suf)]
                break
        salida.append(t)
    return salida


@lru_cache(maxsize=1)
def obligaciones() -> list[dict]:
    return json.loads((config.RAIZ / "normativa" / "obligaciones.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def fragmentos() -> list[dict]:
    """Cláusula → un fragmento por apartado (a), (b)... (o la cláusula entera si no tiene apartados)."""
    salida = []
    for c in normativa.cargar():
        if c["tipo"] not in ("IR", "AMC", "GM"):
            continue
        partes = c["apartados"] or [{"apartado": "", "texto": c["texto"]}]
        for p in partes:
            salida.append({"clausula": c["id"], "apartado": f"({p['apartado']})" if p["apartado"] else "",
                           "tipo": c["tipo"], "titulo": c["titulo"], "texto": p["texto"]})
    return salida


@lru_cache(maxsize=1)
def _bm25_obligaciones():
    return BM25Okapi([tokens(f"{o['tema']} {o['consulta']} {o['texto_norma']}") for o in obligaciones()])


@lru_cache(maxsize=1)
def _bm25_fragmentos():
    return BM25Okapi([tokens(f"{f['clausula']} {f['titulo']} {f['texto']}") for f in fragmentos()])


# ---------------------------------------------------------------- embeddings opcionales (búsqueda híbrida)
def _embeddings_disponibles() -> bool:
    return bool(os.getenv("AZURE_OPENAI_EMBEDDINGS") and config.AZURE_OPENAI_KEY)


def _embed(textos: list[str]) -> np.ndarray:
    from openai import AzureOpenAI
    cli = AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                      api_version=config.AZURE_OPENAI_API_VERSION)
    r = cli.embeddings.create(model=os.getenv("AZURE_OPENAI_EMBEDDINGS"), input=textos)
    m = np.array([d.embedding for d in r.data])
    return m / np.linalg.norm(m, axis=1, keepdims=True)


@lru_cache(maxsize=1)
def _vectores_obligaciones() -> np.ndarray:
    return _embed([f"{o['tema']}. {o['texto_norma']}" for o in obligaciones()])


def _normalizar(x: np.ndarray) -> np.ndarray:
    return x / x.max() if x.max() > 0 else x


# ---------------------------------------------------------------- API
def buscar_obligaciones(consulta: str, k: int = config.TOP_K) -> list[dict]:
    """Devuelve las k obligaciones más parecidas, con 'score_bm25' (absoluto) y 'score' (0-1, híbrido)."""
    bm = _bm25_obligaciones().get_scores(tokens(consulta))
    score = _normalizar(bm)
    if _embeddings_disponibles():
        try:
            sim = _vectores_obligaciones() @ _embed([consulta])[0]
            score = 0.5 * score + 0.5 * _normalizar(np.clip(sim, 0, None))
        except Exception:
            pass   # sin red o sin despliegue → solo BM25
    orden = np.argsort(-score)[:k]
    return [{**obligaciones()[i], "score": float(score[i]), "score_bm25": float(bm[i])} for i in orden]


def buscar_fragmentos(consulta: str, k: int = config.TOP_K, clausula: str | None = None) -> list[dict]:
    """Fragmentos de normativa. Si se da 'clausula', prioriza los de esa cláusula y su AMC/GM."""
    scores = _bm25_fragmentos().get_scores(tokens(consulta))
    frs = fragmentos()
    if clausula:
        scores = scores + np.array([5.0 if clausula in f["clausula"] else 0.0 for f in frs])
    orden = np.argsort(-scores)[:k]
    return [{**frs[i], "score_bm25": float(scores[i])} for i in orden]
