"""
Servicio del Asistente IA (RAG local: ChromaDB + Llama vía Ollama). Nada sale de este ordenador.

    _rag/.venv/bin/python _rag/servidor_rag.py          (Mac)
    _rag\\.venv\\Scripts\\python _rag\\servidor_rag.py     (Windows)

Escucha en http://127.0.0.1:8766 (solo este ordenador). El servidor de la app de Airbus
(airbus/auditor/servidor.py) le reenvía las preguntas del botón «Asistente IA» por /api/asistente.

POST /preguntar  {"pregunta": "...", "datos_app": "...", "historial": [{"r": "u"|"a", "t": "..."}]}
  → {"respuesta": "...", "fuentes": ["corpus_nimbus/01_especificaciones/X.pdf", ...]}
GET  /estado     → {"ok": true, "modelo": "...", "fragmentos": N}

Reglas (CLAUDE.md del proyecto): el LLM no inventa ni calcula; responde SOLO con los fragmentos
recuperados y con los datos que ya calculó la app, y cita de qué archivo sale cada cosa.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402
import rag  # noqa: E402

SISTEMA = (
    "Eres el Asistente IA de la aplicación de auditoría Part-IS (reto Airbus, corpus NIMBUS). "
    "Conversas con un auditor en español, de forma clara y breve (máximo 8 frases o una lista corta). "
    "Usa SOLO dos fuentes: (1) DATOS DE LA APP, que son resultados ya calculados por la aplicación "
    "(hallazgos, métricas, decisiones), y (2) FRAGMENTOS DE DOCUMENTOS recuperados del corpus y del código. "
    "No inventes requisitos, cláusulas, cifras ni nombres de documento; no hagas cálculos nuevos. "
    "Cuando uses un fragmento, cita su archivo entre corchetes, p. ej. [SRS-SEC-NIMBUS-GCS.pdf]. "
    "Si la información no está en esas fuentes, dilo y sugiere qué buscar. "
    "Si te piden un juicio de cumplimiento, da tu valoración como propuesta para que la revise una persona."
)
MAX_HIST = 6          # turnos previos que se envían al modelo
MAX_DATOS = 4000      # caracteres de DATOS DE LA APP


def responder(pregunta: str, datos_app: str = "", historial: list | None = None) -> dict:
    # Búsqueda: la pregunta + la última pregunta del usuario (para preguntas de seguimiento «¿y ese?»)
    previas = [h.get("t", "") for h in (historial or []) if h.get("r") == "u"]
    consulta = (previas[-1] + " " + pregunta) if previas else pregunta
    docs, metas = rag.retrieve(consulta, k=8, folder=cfg.ASISTENTE_CARPETAS)
    contexto = "\n\n---\n\n".join(docs)[: cfg.MAX_CONTEXT_CHARS]
    fuentes = list(dict.fromkeys(m["source"] for m in metas))

    mensajes = [{"role": "system", "content": SISTEMA}]
    for h in (historial or [])[-MAX_HIST:]:
        if h.get("t"):
            mensajes.append({"role": "user" if h.get("r") == "u" else "assistant", "content": str(h["t"])[:1500]})
    mensajes.append({"role": "user", "content": (
        f"DATOS DE LA APP:\n{(datos_app or '(sin datos)')[:MAX_DATOS]}\n\n"
        f"FRAGMENTOS DE DOCUMENTOS:\n{contexto or '(no se encontró nada relevante)'}\n\n"
        f"PREGUNTA: {pregunta}")})
    out = rag.ollama.chat(model=cfg.LLM_MODEL, messages=mensajes,
                          options={"temperature": 0.2, "num_ctx": cfg.NUM_CTX})
    return {"respuesta": out["message"]["content"].strip(), "fuentes": fuentes}


class Manejador(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/estado":
            return self._json(200, {"ok": True, "modelo": cfg.LLM_MODEL, "fragmentos": rag.get_collection().count()})
        self._json(404, {"error": "No encontrado"})

    def do_POST(self):
        if self.path != "/preguntar":
            return self._json(404, {"error": "No encontrado"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            b = json.loads(self.rfile.read(min(n, 200_000)) or b"{}")
            pregunta = str(b.get("pregunta", "")).strip()[:2000]
            if not pregunta:
                return self._json(400, {"error": "Falta la pregunta"})
            self._json(200, responder(pregunta, str(b.get("datos_app", "")), b.get("historial") or []))
        except Exception as e:   # Ollama apagado, índice vacío, JSON roto…
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):   # consola limpia: solo las preguntas
        pass


def main():
    try:
        n = rag.get_collection().count()
        rag.ollama.list()
    except Exception as e:
        sys.exit(f"No puedo arrancar: {e}\n  → ¿Está abierta la app Ollama? ¿Ejecutaste antes `rag.py ingest`?")
    srv = ThreadingHTTPServer(("127.0.0.1", cfg.ASISTENTE_PUERTO), Manejador)
    print(f"\n  Asistente IA listo en http://127.0.0.1:{cfg.ASISTENTE_PUERTO}  ·  modelo {cfg.LLM_MODEL}  ·  "
          f"{n} fragmentos  ·  busca en: {', '.join(cfg.ASISTENTE_CARPETAS)}\n  Deja esta ventana abierta. Ctrl+C para apagarlo.\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
