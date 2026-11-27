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
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402
import rag  # noqa: E402

SISTEMA = (
    "Eres el Asistente IA de la aplicación de auditoría Part-IS (reto Airbus, corpus NIMBUS). "
    "Conversas con un auditor en español. Responde CORTO: 1 a 3 frases directas (o una lista de 3 puntos como máximo), sin saludos, sin despedidas y sin empezar con «Según el fragmento» ni «Según la guía». "
    "Usa SOLO dos fuentes: (1) DATOS DE LA APP, que son resultados ya calculados por la aplicación "
    "(hallazgos, métricas, decisiones), y (2) FRAGMENTOS DE DOCUMENTOS recuperados del corpus y del código. "
    "No inventes requisitos, cláusulas, cifras ni nombres de documento; no hagas cálculos nuevos. "
    "No nombres archivos de la aplicación (GUIA_APLICACION.md, README.md); solo si la respuesta sale de un PDF del corpus, nombra ese documento por su código (p. ej. STD-SEC-001). "
    "Si la información no está en esas fuentes, dilo y sugiere qué buscar. "
    "Si te piden un juicio de cumplimiento, da tu valoración como propuesta para que la revise una persona. "
    "IMPORTANTE: los fragmentos de GUIA_APLICACION.md y auditor/README.md explican LA APLICACIÓN (pantallas, botones, "
    "chat, exportar, métricas como el F1 0,932, cómo se ejecuta y qué se entrega). Para preguntas sobre cómo usar la "
    "aplicación o sobre sus resultados, responde SOLO con esos fragmentos. Los PDF del corpus NIMBUS son los documentos "
    "que se auditan: úsalos solo para preguntas sobre su contenido (requisitos, plazos, estándares), nunca como "
    "instrucciones de la aplicación. "
    "No añadas botones, pantallas, opciones ni pasos que no aparezcan escritos en los fragmentos; "
    "si no sabes si algo existe, no lo menciones. Termina cuando hayas contado lo que dicen los fragmentos. "
    "Para preguntas sobre el estado de la revisión o del equipo (mensajes, avisos sin leer, menciones, quién escribió, decisiones, pendientes, documentos completados, ediciones, versiones, quién está conectado) usa SOLO DATOS DE LA APP y copia las cifras tal cual aparecen: nunca sumes, restes ni estimes. Si el dato no aparece en DATOS DE LA APP, responde «No tengo ese dato en la app» y di en qué pantalla mirarlo."
)
CODIGO_DOC = re.compile(r"\b[A-Z]{2,6}(?:-[A-Z0-9]{1,8}){1,3}\b")
PALABRAS_APP = ("mensaje", "chat", "escrib", "mencion", "leid", "notificac", "aviso", "mandaron", "enviaron", "dijo",
                "aprob", "rechaz", "decid", "decision", "pendiente", "me quedan", "por revisar", "completad", "en revision",
                "escalad", "vencid", "prioridad", "compartid", "cargad", "atrasad", "editad", "versiones del pdf", "versiones guardadas", "guardado versiones", "conectad", "en linea", "comentari", "grupo", "privado")


def _norm(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


GENERICAS = {"seccion", "pantalla", "aplicacion", "cuantos", "cuantas", "tiempo", "durante", "auditor", "documento",
             "puedo", "quiero", "compañero", "companero", "hallazgos", "encontro", "cuanto"}


def es_de_la_app(pregunta: str) -> bool:
    """¿Pregunta por el estado de la revisión o del equipo (chat, decisiones, pendientes…)?"""
    p = _norm(pregunta)
    return any(w in p for w in PALABRAS_APP) and not re.search(r"\bcomo\b|\bpuedo\b|\bpuede\b|\bque es\b|\bque son\b|\bpara que\b|\bsirve\b|\bexplica|\bse modifica\b|\bdonde\b", p)


VACIAS = {"que", "cual", "cuales", "cuantos", "cuantas", "quien", "tengo", "tiene", "hay", "han", "ha", "los", "las",
          "del", "por", "para", "con", "una", "uno", "mis", "yo", "me", "mi", "se", "en", "el", "la", "de", "y"}


def lineas_relevantes(pregunta: str, datos: str, k: int = 4) -> list[str]:
    """Para preguntas de estado: las líneas de DATOS DE LA APP (ya calculadas por la app) que más palabras comparten
    con la pregunta, comparando las 5 primeras letras («aprobado» encaja con «aprobados»). Solo se quedan las de
    puntuación máxima (como mucho k). «yo / he / mis» cuenta como el nombre de quien pregunta."""
    lineas = [l for l in datos.splitlines() if l.strip()]
    p = re.sub(r"\b(mandaron|enviaron|mandado|enviado|dijo|dicho|escribieron|escrito)\b", "escribio", _norm(pregunta))
    raices = {w[:5] for w in re.findall(r"[a-z0-9]+", p) if len(w) > 2 and w not in VACIAS}
    m = re.search(r"Usuario que pregunta: ([^·.]+)", datos)
    if m and re.search(r"\b(yo|he|mis|mi|me)\b", p):
        raices.add(_norm(m.group(1).strip())[:5])
    if len(lineas) < 2 or not raices:
        return []
    def puntos(l):
        return len(raices & {w[:5] for w in re.findall(r"[a-z0-9]+", _norm(l))})
    top = max(puntos(l) for l in lineas[1:])
    return [l for l in lineas[1:] if top > 0 and puntos(l) == top][:k]


def buscar(consulta: str, pregunta: str) -> tuple[list, list]:
    """Tres búsquedas: guía de la aplicación (siempre presente), documentos que se nombran por su código
    (p. ej. STD-SEC-001) y el corpus en general. Así los 1.000+ fragmentos del corpus no tapan a la guía."""
    col = rag.get_collection()
    emb = rag.embed([consulta])
    vistos, docs, metas = set(), [], []

    def anadir(res):
        for i, d, m in zip(res["ids"][0], res["documents"][0], res["metadatas"][0]):
            if i not in vistos:
                vistos.add(i); docs.append(d); metas.append(m)

    anadir(col.query(query_embeddings=emb, n_results=3 if es_de_la_app(pregunta) else 4, where={"folder": "airbus"}))
    # Búsqueda por palabra exacta en la guía (las 2 palabras más largas de la pregunta): encuentra la pregunta
    # frecuente justa aunque la búsqueda por significado no la ponga arriba
    largas = sorted({w for w in re.findall(r"\w+", pregunta.lower()) if len(w) >= 6 and _norm(w) not in GENERICAS}, key=len, reverse=True)[:2]
    for w in largas:
        try:
            anadir(col.query(query_embeddings=emb, n_results=2, where={"folder": "airbus"},
                             where_document={"$contains": w}))
        except Exception:
            pass
    if es_de_la_app(pregunta):
        return docs, metas                    # estado de la app: la respuesta está en DATOS DE LA APP, no en los PDF
    for cod in [c for c in dict.fromkeys(CODIGO_DOC.findall(pregunta.upper())) if any(ch.isdigit() for ch in c)][:2]:
        try:
            anadir(col.query(query_embeddings=emb, n_results=4, where={"folder": "corpus_nimbus"},
                             where_document={"$contains": cod}))
        except Exception:
            pass                              # ningún fragmento contiene ese código
    anadir(col.query(query_embeddings=emb, n_results=4, where={"folder": "corpus_nimbus"}))
    return docs, metas
MAX_HIST = 6          # turnos previos que se envían al modelo
MAX_DATOS = 6000      # caracteres de DATOS DE LA APP


def responder(pregunta: str, datos_app: str = "", historial: list | None = None) -> dict:
    # Estado de la app (chat, decisiones, pendientes…): responde el código con las cifras exactas, sin LLM.
    # Regla del proyecto: el LLM no cuenta ni calcula; un modelo de 3B mezclaba cifras de líneas distintas.
    app = es_de_la_app(pregunta)
    if app:
        lineas = lineas_relevantes(pregunta, (datos_app or "")[:MAX_DATOS])
        if lineas:
            return {"respuesta": "\n".join("• " + l for l in lineas), "fuentes": []}
    # Búsqueda: la pregunta + la última pregunta del usuario (para preguntas de seguimiento «¿y ese?»)
    previas = [h.get("t", "") for h in (historial or []) if h.get("r") == "u"]
    consulta = (previas[-1] + " " + pregunta) if previas else pregunta
    docs, metas = buscar(consulta, pregunta)
    contexto = "\n\n---\n\n".join(docs)[: cfg.MAX_CONTEXT_CHARS]
    fuentes = list(dict.fromkeys(m["source"] for m in metas))

    mensajes = [{"role": "system", "content": SISTEMA}]
    for h in (historial or [])[-MAX_HIST:]:
        if h.get("t"):
            mensajes.append({"role": "user" if h.get("r") == "u" else "assistant", "content": str(h["t"])[:1500]})
    # Los datos de la app van justo antes de la pregunta: el modelo pequeño atiende mejor a lo último que lee
    datos = (datos_app or "(sin datos)")[:MAX_DATOS]
    pista = ("La respuesta está en DATOS DE LA APP: busca ahí la línea que corresponde y copia sus cifras y nombres.\n"
             if app else "")
    mensajes.append({"role": "user", "content": (
        f"FRAGMENTOS DE DOCUMENTOS:\n{contexto or '(no se encontró nada relevante)'}\n\n"
        f"DATOS DE LA APP:\n{datos}\n\n"
        f"{pista}PREGUNTA: {pregunta}")})
    out = rag.ollama.chat(model=cfg.LLM_MODEL, messages=mensajes,
                          options={"temperature": 0 if app else 0.2, "num_ctx": cfg.NUM_CTX, "num_predict": 220})
    respuesta = out["message"]["content"].strip()
    if app and not cifras_verificadas(respuesta, datos + " " + pregunta + " " + contexto):
        # Verificador: la IA ha escrito una cifra que no está en los datos → se enseñan los datos tal cual
        lineas = [l for l in datos.splitlines()[1:4] if l.strip()] or datos.splitlines()
        respuesta = "Según los datos de la app:\n" + "\n".join("- " + l for l in lineas)
    return {"respuesta": respuesta, "fuentes": fuentes}


def cifras_verificadas(respuesta: str, datos: str) -> bool:
    """Toda cifra de la respuesta tiene que aparecer en los datos (o en la pregunta). La IA no cuenta ni calcula."""
    permitidas = set(re.findall(r"\d+", datos))
    return all(n in permitidas for n in re.findall(r"\d+", respuesta))


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
            try:
                r = responder(pregunta, str(b.get("datos_app", "")), b.get("historial") or [])
            except Exception:                 # primer uso tras arrancar (índice o modelo en frío): un reintento
                r = responder(pregunta, str(b.get("datos_app", "")), b.get("historial") or [])
            self._json(200, r)
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
