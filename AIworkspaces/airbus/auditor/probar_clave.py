"""Comprueba que la clave del .env funciona (no imprime la clave). Ejecutar: .venv\\Scripts\\python probar_clave.py"""
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
clave = os.getenv("AZURE_API_KEY", "").strip()
if not clave:
    raise SystemExit("Falta la clave: pégala en el archivo .env (línea AZURE_API_KEY=) y guarda.")

cli = Anthropic(api_key=clave, base_url=os.getenv("ANTHROPIC_BASE_URL"))
for modelo in (os.getenv("MODELO_RAPIDO"), os.getenv("MODELO_AUDITOR")):
    try:
        r = cli.messages.create(model=modelo, max_tokens=40,
                                messages=[{"role": "user", "content": "Responde solo: funciona"}])
        print(f"OK  {modelo}: {r.content[0].text.strip()}")
    except Exception as e:
        print(f"MAL {modelo}: {type(e).__name__}: {str(e)[:200]}")
