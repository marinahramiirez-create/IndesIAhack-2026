# AIworkspaces

Coloca cada proyecto en su propia carpeta dentro de `AIworkspaces/`. El sistema RAG de `_rag/`
lee el contenido de cada carpeta, lo indexa en **ChromaDB** y usa **Llama** (vía Ollama, 100 % local)
para generar la documentación.

```
AIworkspaces/
├── _rag/                      # sistema RAG (no se documenta a sí mismo)
│   ├── rag.py                 # ingest / document / ask
│   ├── config.py              # modelos, extensiones, tamaños de fragmento
│   ├── requirements.txt
│   ├── .venv/                 # entorno Python
│   └── chroma_db/             # base vectorial persistente (se crea sola)
├── documentar.bat             # atajo: indexa + documenta todo
├── DOCUMENTACION_GENERAL.md   # índice generado
└── <TuProyecto>/
    └── DOCUMENTACION.md       # generado por carpeta
```

## Instalación (una sola vez)

1. Instala Ollama: https://ollama.com/download (o `winget install Ollama.Ollama`).
2. Descarga los modelos:
   ```
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ```
3. El entorno Python ya está creado en `_rag/.venv`. Si hace falta recrearlo (usa Python 3.13 o
   anterior: chromadb no se instala con 3.14/3.15; en Mac: `python3.13 -m venv _rag/.venv`):
   ```
   python -m venv _rag\.venv
   _rag\.venv\Scripts\pip install -r _rag\requirements.txt
   ```

## Uso

Desde `AIworkspaces`:

| Comando | Qué hace |
|---|---|
| `documentar.bat` | Indexa todo y genera la documentación de todas las carpetas |
| `_rag\.venv\Scripts\python _rag\rag.py ingest` | Indexa / actualiza ChromaDB (solo archivos nuevos o modificados) |
| `_rag\.venv\Scripts\python _rag\rag.py document` | Genera `DOCUMENTACION.md` en cada carpeta + `DOCUMENTACION_GENERAL.md` |
| `_rag\.venv\Scripts\python _rag\rag.py document MiCarpeta` | Documenta solo una carpeta |
| `_rag\.venv\Scripts\python _rag\rag.py ask "¿qué hace X?"` | Pregunta puntual con fuentes citadas |
| `_rag\.venv\Scripts\python _rag\rag.py ask` | Chat interactivo |
| `... ask --folder MiCarpeta` | Limita la búsqueda a una carpeta |

## Cómo funciona

1. **Ingesta**: recorre cada carpeta, lee `.py .ipynb .md .txt .pdf .docx .csv .json ...`
   (ver `config.py`), los parte en fragmentos de ~1200 caracteres y guarda sus embeddings
   (`nomic-embed-text`) en ChromaDB con metadatos `folder` y `source`.
2. **Recuperación**: para cada carpeta lanza varias consultas (propósito, ejecución, componentes,
   datos, pendientes) filtrando por `folder`.
3. **Generación**: Llama recibe la estructura de archivos + los fragmentos recuperados y redacta
   el `DOCUMENTACION.md`; después resume todo en `DOCUMENTACION_GENERAL.md`.

Para usar un modelo más potente cambia `LLM_MODEL` en `_rag/config.py` (p. ej. `llama3.1:8b`).
