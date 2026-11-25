"""
Verifica las conexiones configuradas en .env SIN mostrar nunca las claves.

Ejecutar desde airbus/:
    python -m src.verificar_conexiones

Prueba, de lo que esté configurado:
  1. Azure OpenAI · chat        (el despliegue de AZURE_OPENAI_DEPLOYMENT responde)
  2. Azure OpenAI · embeddings  (AZURE_OPENAI_EMBEDDINGS, opcional)
  3. Azure AI Search            (lista los índices, opcional)
  4. Databricks                 (quién soy, clústeres y volumen del equipo, opcional)
  5. Base de datos              (SQLite local o PostgreSQL de Azure)
"""
import os
import time

import requests

import config


def _host(url: str) -> str:
    """Solo el dominio, para identificar el recurso sin enseñar nada sensible."""
    return url.split("//")[-1].split("/")[0] if url else "—"


def _ok(nombre, detalle=""):
    print(f"  ✅ {nombre}" + (f" · {detalle}" if detalle else ""))
    return True


def _mal(nombre, detalle, pista=""):
    print(f"  ❌ {nombre} · {detalle}")
    if pista:
        print(f"     → {pista}")
    return False


def _omitido(nombre, motivo):
    print(f"  ⏭️  {nombre} · {motivo}")
    return None


def _error_corto(e: Exception) -> str:
    t = str(e).replace("\n", " ")
    for clave in [config.AZURE_OPENAI_KEY, os.getenv("AZURE_SEARCH_KEY", ""), os.getenv("DATABRICKS_TOKEN", "")]:
        if clave:
            t = t.replace(clave, "***")       # por si una librería repite la clave en el error
    return t[:220]


def azure_openai_chat():
    nombre = "Azure OpenAI · chat"
    if not (config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_KEY and config.AZURE_OPENAI_DEPLOYMENT) \
            or "NOMBRE" in config.AZURE_OPENAI_ENDPOINT:
        return _omitido(nombre, "faltan AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_KEY / AZURE_OPENAI_DEPLOYMENT en .env")
    from openai import AzureOpenAI
    cli = AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                      api_version=config.AZURE_OPENAI_API_VERSION)
    try:
        t0 = time.time()
        r = cli.chat.completions.create(model=config.AZURE_OPENAI_DEPLOYMENT,
                                        messages=[{"role": "user", "content": 'Responde solo con JSON: {"ok": true}'}],
                                        response_format={"type": "json_object"})
        modelo = getattr(r, "model", "?")
        ok = _ok(nombre, f"{_host(config.AZURE_OPENAI_ENDPOINT)} · despliegue '{config.AZURE_OPENAI_DEPLOYMENT}' "
                         f"(modelo {modelo}) · JSON ok · {time.time() - t0:.1f} s")
        if config.LLM_PROVEEDOR != "azure":
            print("     ⚠️  Funciona, pero LLM_PROVEEDOR no es 'azure': el auditor NO lo usará hasta que lo cambies.")
        return ok
    except Exception as e:
        msg = _error_corto(e)
        pista = ""
        if "DeploymentNotFound" in msg or "404" in msg:
            pista = "El nombre del DESPLIEGUE no existe. Míralo en Azure AI Foundry → Deployments (no es el nombre del modelo)."
        elif "401" in msg or "Access denied" in msg:
            pista = "Clave o endpoint incorrectos (¿la clave es de este recurso?)."
        elif "api-version" in msg.lower() or "API version" in msg:
            pista = "Prueba otra AZURE_OPENAI_API_VERSION (p. ej. 2024-10-21 o 2025-01-01-preview)."
        elif "response_format" in msg:
            pista = "Este modelo no admite JSON mode: dímelo y lo adaptamos."
        return _mal(nombre, msg, pista)


def azure_openai_embeddings():
    nombre = "Azure OpenAI · embeddings"
    dep = os.getenv("AZURE_OPENAI_EMBEDDINGS", "")
    if not dep or not config.AZURE_OPENAI_KEY:
        return _omitido(nombre, "opcional: AZURE_OPENAI_EMBEDDINGS vacío (se usa solo BM25)")
    from openai import AzureOpenAI
    cli = AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_KEY,
                      api_version=config.AZURE_OPENAI_API_VERSION)
    try:
        r = cli.embeddings.create(model=dep, input=["records retention period"])
        return _ok(nombre, f"despliegue '{dep}' · vector de {len(r.data[0].embedding)} dimensiones")
    except Exception as e:
        return _mal(nombre, _error_corto(e), "Revisa el nombre del despliegue de embeddings.")


def azure_search():
    nombre = "Azure AI Search"
    ep, key = os.getenv("AZURE_SEARCH_ENDPOINT", ""), os.getenv("AZURE_SEARCH_KEY", "")
    if not (ep and key):
        return _omitido(nombre, "opcional: sin AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY")
    try:
        r = requests.get(f"{ep.rstrip('/')}/indexes?api-version=2023-11-01&$select=name",
                         headers={"api-key": key}, timeout=20)
        r.raise_for_status()
        indices = [i["name"] for i in r.json().get("value", [])]
        return _ok(nombre, f"{_host(ep)} · {len(indices)} índices: {', '.join(indices) or '(ninguno todavía)'}")
    except Exception as e:
        return _mal(nombre, _error_corto(e), "Comprueba endpoint (https://NOMBRE.search.windows.net) y clave de administración.")


def databricks():
    nombre = "Databricks"
    host, token = os.getenv("DATABRICKS_HOST", "").rstrip("/"), os.getenv("DATABRICKS_TOKEN", "")
    if not (host and token):
        return _omitido(nombre, "opcional: sin DATABRICKS_HOST / DATABRICKS_TOKEN")
    cab = {"Authorization": f"Bearer {token}"}
    try:
        yo = requests.get(f"{host}/api/2.0/preview/scim/v2/Me", headers=cab, timeout=20)
        yo.raise_for_status()
        usuario = yo.json().get("userName", "?")
        cl = requests.get(f"{host}/api/2.0/clusters/list", headers=cab, timeout=20).json().get("clusters", [])
        estados = ", ".join(f"{c.get('cluster_name')} ({c.get('state')})" for c in cl) or "ninguno visible"
        _ok(nombre, f"{_host(host)} · conectado como {usuario.split('@')[0]}… · clústeres: {estados}")
        cat = os.getenv("DATABRICKS_CATALOGO", "")
        if cat:
            ruta = f"/Volumes/{cat}/raw_sch/raw_vol/datos_reto/"
            v = requests.get(f"{host}/api/2.0/fs/directories{ruta}", headers=cab, timeout=20)
            if v.ok:
                nombres = [x.get("name") for x in v.json().get("contents", [])]
                _ok("Databricks · volumen datos_reto", f"{ruta} · {len(nombres)} elementos: {', '.join(nombres[:10])}")
            else:
                _mal("Databricks · volumen datos_reto", f"HTTP {v.status_code} en {ruta}", "Revisa DATABRICKS_CATALOGO.")
        return True
    except Exception as e:
        return _mal(nombre, _error_corto(e), "Host = URL del workspace; token = Settings → Developer → Access tokens.")


def base_datos():
    nombre = "Base de datos"
    url = config.DATABASE_URL
    tipo = "PostgreSQL (Azure)" if url.startswith("postgresql") else "SQLite (local)"
    try:
        from sqlalchemy import text
        from src import db
        with db.engine.connect() as con:
            con.execute(text("SELECT 1"))
        return _ok(nombre, tipo)
    except Exception as e:
        msg = _error_corto(e)
        pista = ""
        if "psycopg" in msg or "libpq" in msg or "Application Control" in msg:
            pista = ("En este portátil Smart App Control bloquea el driver de PostgreSQL. "
                     "Usa SQLite local (deja DATABASE_URL comentado) o conecta desde otro portátil.")
        return _mal(nombre, f"{tipo}: {msg}", pista)


if __name__ == "__main__":
    print(f"\nVerificando conexiones (.env de {config.RAIZ.name}/) — las claves nunca se muestran\n")
    resultados = [azure_openai_chat(), azure_openai_embeddings(), azure_search(), databricks(), base_datos()]
    ok = sum(r is True for r in resultados)
    mal = sum(r is False for r in resultados)
    print(f"\nResumen: {ok} correctas · {mal} con error · {resultados.count(None)} sin configurar")
