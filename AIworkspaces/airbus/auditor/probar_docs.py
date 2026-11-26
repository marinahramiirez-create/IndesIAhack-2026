"""Prueba rápida del auditor en unos documentos (sin transcribir escaneados). Uso:
    python probar_docs.py SRS-SEC-C2L,REG-ACC-2026 salidas/prueba.csv
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import auditar
from src import ingesta, referencias

from src.rutas import CORPUS  # noqa: E402  (ruta del corpus: .env o carpetas habituales)

codigos = sys.argv[1].split(",")
salida = Path(sys.argv[2])
t0 = time.time()
docs = [ingesta.leer(f, vision=True) for f in sorted(CORPUS.rglob("*.pdf"))]
bloque = referencias.bloque(docs)
objetivo = [d for d in docs if d.codigo in codigos]
todos, trazas = [], []
with ThreadPoolExecutor(6) as ex:
    for d, (hall, traza) in zip(objetivo, ex.map(lambda d: auditar.auditar_doc(d, docs, bloque, True), objetivo)):
        todos += hall
        trazas += traza
        print(f"{d.codigo}: {len(hall)} aceptados, {sum(not t['aceptado'] for t in traza)} descartados "
              f"· relacionados {traza[0]['relacionados'] if traza else []} · {time.time() - t0:.0f} s", flush=True)
auditar.escribir(todos, salida)
with open(salida.with_name(salida.stem + "_traza.jsonl"), "w", encoding="utf-8") as f:
    for t in trazas:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
print(f"{len(todos)} hallazgos → {salida} ({time.time() - t0:.0f} s)")
