"""
RAG de documentación para AIworkspaces.

Indexa el contenido de cada carpeta de AIworkspaces en ChromaDB (embeddings
locales con Ollama) y usa Llama (vía Ollama) para:
  - generar un DOCUMENTACION.md dentro de cada carpeta,
  - generar un índice general en AIworkspaces/DOCUMENTACION_GENERAL.md,
  - responder preguntas sobre el contenido del workspace.

Uso:
    python rag.py ingest              # indexa / actualiza ChromaDB (incremental)
    python rag.py document            # genera la documentación de todas las carpetas
    python rag.py document MiCarpeta  # documenta solo una carpeta
    python rag.py ask "¿Qué hace el proyecto X?"
    python rag.py ask                 # modo chat interactivo
    python rag.py all                 # ingest + document
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import chromadb
import ollama

import config as cfg

# --------------------------------------------------------------------------
# Lectura de archivos
# --------------------------------------------------------------------------


def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        if ext == ".docx":
            import docx

            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        if ext == ".ipynb":
            nb = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            cells = []
            for c in nb.get("cells", []):
                src = c.get("source", "")
                cells.append("".join(src) if isinstance(src, list) else src)
            return "\n\n".join(cells)
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:  # archivo corrupto, protegido, etc.
        print(f"  [aviso] No se pudo leer {path.name}: {e}")
        return ""


def iter_files(folder: Path):
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        if any(part in cfg.IGNORED_DIRS for part in p.relative_to(cfg.WORKSPACE).parts):
            continue
        if p.name in cfg.GENERATED_FILES:
            continue
        if p.suffix.lower() not in cfg.EXTENSIONS:
            continue
        if p.stat().st_size > cfg.MAX_FILE_BYTES:
            continue
        yield p


def top_folders():
    return sorted(
        d for d in cfg.WORKSPACE.iterdir()
        if d.is_dir() and d.name not in cfg.IGNORED_DIRS and not d.name.startswith(".")
    )


def chunk_text(text: str, size: int = cfg.CHUNK_SIZE, overlap: int = cfg.CHUNK_OVERLAP):
    text = text.strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        # intenta cortar en un salto de línea para no partir frases
        if end < len(text):
            nl = text.rfind("\n", start + size // 2, end)
            if nl != -1:
                end = nl
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


# --------------------------------------------------------------------------
# ChromaDB + Ollama
# --------------------------------------------------------------------------


def get_collection():
    client = chromadb.PersistentClient(path=str(cfg.CHROMA_DIR))
    return client.get_or_create_collection(cfg.COLLECTION, metadata={"hnsw:space": "cosine"})


def embed(texts):
    return ollama.embed(model=cfg.EMBED_MODEL, input=texts)["embeddings"]


def file_hash(path: Path) -> str:
    st = path.stat()
    return hashlib.md5(f"{st.st_size}-{st.st_mtime_ns}".encode()).hexdigest()


def ingest():
    col = get_collection()
    existing = col.get(include=["metadatas"])
    indexed = {}  # ruta relativa -> hash
    for m in existing["metadatas"]:
        indexed[m["source"]] = m["hash"]

    seen = set()
    added = skipped = 0
    for folder in top_folders():
        print(f"> {folder.name}")
        for path in iter_files(folder):
            rel = path.relative_to(cfg.WORKSPACE).as_posix()
            seen.add(rel)
            h = file_hash(path)
            if indexed.get(rel) == h:
                skipped += 1
                continue
            col.delete(where={"source": rel})  # versión anterior del archivo
            chunks = chunk_text(read_file(path))
            if not chunks:
                continue
            for i in range(0, len(chunks), 32):
                batch = chunks[i:i + 32]
                col.add(
                    ids=[f"{rel}::{i + j}" for j in range(len(batch))],
                    documents=[f"[Archivo: {rel}]\n{c}" for c in batch],
                    embeddings=embed(batch),
                    metadatas=[{"folder": folder.name, "source": rel, "hash": h}] * len(batch),
                )
            added += 1
            print(f"   + {rel} ({len(chunks)} fragmentos)")

    # elimina del índice archivos que ya no existen
    removed = 0
    for rel in set(indexed) - seen:
        col.delete(where={"source": rel})
        removed += 1
    print(f"\nIndexados: {added} | sin cambios: {skipped} | eliminados: {removed} | "
          f"fragmentos totales: {col.count()}")


def retrieve(query: str, k: int = cfg.TOP_K, folder: str | None = None):
    col = get_collection()
    if col.count() == 0:
        sys.exit("ChromaDB está vacío. Ejecuta primero: python rag.py ingest")
    res = col.query(
        query_embeddings=embed([query]),
        n_results=min(k, col.count()),
        where={"folder": folder} if folder else None,
    )
    return res["documents"][0], res["metadatas"][0]


def llm(system: str, prompt: str) -> str:
    out = ollama.chat(
        model=cfg.LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        options={"temperature": 0.2, "num_ctx": cfg.NUM_CTX},
    )
    return out["message"]["content"].strip()


# --------------------------------------------------------------------------
# Generación de documentación
# --------------------------------------------------------------------------

SYSTEM_DOC = (
    "Eres un documentador técnico. Escribes en español, en Markdown, de forma clara y "
    "concisa. Usa SOLO la información del contexto proporcionado; si algo no se puede "
    "deducir, dilo explícitamente en lugar de inventarlo."
)

DOC_QUERIES = [
    "propósito, objetivo y descripción general del proyecto",
    "cómo instalar, configurar y ejecutar; dependencias y requisitos",
    "funciones, clases, módulos principales y su responsabilidad",
    "datos de entrada, salida, formatos y archivos utilizados",
    "resultados, conclusiones, pendientes o TODO",
]


def tree(folder: Path, max_lines: int = 80) -> str:
    lines = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if any(part in cfg.IGNORED_DIRS for part in rel.parts) or p.name in cfg.GENERATED_FILES:
            continue
        lines.append("  " * (len(rel.parts) - 1) + ("📁 " if p.is_dir() else "") + p.name)
        if len(lines) >= max_lines:
            lines.append("  ...")
            break
    return "\n".join(lines) or "(vacía)"


def document_folder(folder: Path) -> str:
    print(f"> Documentando {folder.name} ...")
    docs, seen = [], set()
    for q in DOC_QUERIES:
        try:
            d, _ = retrieve(f"{folder.name}: {q}", k=cfg.TOP_K, folder=folder.name)
        except Exception:
            d = []
        for chunk in d:
            if chunk not in seen:
                seen.add(chunk)
                docs.append(chunk)
    context = "\n\n---\n\n".join(docs)[: cfg.MAX_CONTEXT_CHARS]
    structure = tree(folder)

    prompt = f"""Documenta la carpeta "{folder.name}".

ESTRUCTURA DE ARCHIVOS:
{structure}

FRAGMENTOS RELEVANTES DEL CONTENIDO:
{context or "(no hay archivos de texto indexados en esta carpeta)"}

Genera un documento Markdown con estas secciones:
# {folder.name}
## Resumen
## Estructura de la carpeta (explica brevemente cada archivo/subcarpeta importante)
## Componentes principales
## Cómo usar / ejecutar
## Dependencias y requisitos
## Observaciones y pendientes
"""
    md = llm(SYSTEM_DOC, prompt)
    md += ("\n\n---\n*Documentación generada automáticamente con RAG "
           f"(ChromaDB + {cfg.LLM_MODEL}). Regenerar con `python _rag/rag.py document {folder.name}`.*\n")
    (folder / cfg.DOC_FILENAME).write_text(md, encoding="utf-8")
    print(f"   -> {folder.name}/{cfg.DOC_FILENAME}")
    return md


def document(only: str | None = None):
    folders = top_folders()
    if only:
        folders = [f for f in folders if f.name == only]
        if not folders:
            sys.exit(f"No existe la carpeta '{only}' en {cfg.WORKSPACE}")
    if not folders:
        sys.exit(f"No hay carpetas que documentar en {cfg.WORKSPACE}")

    summaries = {}
    for f in folders:
        md = document_folder(f)
        summaries[f.name] = md[:1500]

    if only:
        return
    print("> Generando índice general ...")
    joined = "\n\n".join(f"### {k}\n{v}" for k, v in summaries.items())
    index = llm(
        SYSTEM_DOC,
        "A partir de la documentación de cada carpeta, escribe un índice general del "
        "workspace en Markdown: una tabla (Carpeta | Descripción en una línea | Tecnologías) "
        "y luego un párrafo de visión general y posibles relaciones entre carpetas.\n\n" + joined,
    )
    links = "\n".join(f"- [{n}](./{n}/{cfg.DOC_FILENAME})" for n in summaries)
    out = f"# AIworkspaces — Documentación general\n\n{index}\n\n## Enlaces\n{links}\n"
    (cfg.WORKSPACE / "DOCUMENTACION_GENERAL.md").write_text(out, encoding="utf-8")
    print("   -> DOCUMENTACION_GENERAL.md")


# --------------------------------------------------------------------------
# Preguntas
# --------------------------------------------------------------------------

SYSTEM_QA = (
    "Eres un asistente que responde preguntas sobre los proyectos de AIworkspaces. "
    "Responde en español usando SOLO el contexto. Cita los archivos fuente entre corchetes. "
    "Si la respuesta no está en el contexto, dilo."
)


def ask(question: str, folder: str | None = None):
    docs, metas = retrieve(question, folder=folder)
    context = "\n\n---\n\n".join(docs)[: cfg.MAX_CONTEXT_CHARS]
    answer = llm(SYSTEM_QA, f"CONTEXTO:\n{context}\n\nPREGUNTA: {question}")
    sources = sorted({m["source"] for m in metas})
    print(f"\n{answer}\n\nFuentes: " + ", ".join(sources) + "\n")


def chat(folder: str | None = None):
    print("Chat RAG de AIworkspaces (escribe 'salir' para terminar)")
    while True:
        try:
            q = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"salir", "exit", "quit"}:
            break
        if q:
            ask(q, folder)


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="RAG de documentación para AIworkspaces")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="Indexa/actualiza las carpetas en ChromaDB")
    d = sub.add_parser("document", help="Genera DOCUMENTACION.md por carpeta + índice general")
    d.add_argument("folder", nargs="?")
    a = sub.add_parser("ask", help="Pregunta sobre el contenido (sin pregunta = chat)")
    a.add_argument("question", nargs="*")
    a.add_argument("--folder", help="Restringe la búsqueda a una carpeta")
    sub.add_parser("all", help="ingest + document")
    args = ap.parse_args()

    if args.cmd == "ingest":
        ingest()
    elif args.cmd == "document":
        document(args.folder)
    elif args.cmd == "ask":
        if args.question:
            ask(" ".join(args.question), args.folder)
        else:
            chat(args.folder)
    elif args.cmd == "all":
        ingest()
        document()


if __name__ == "__main__":
    main()
