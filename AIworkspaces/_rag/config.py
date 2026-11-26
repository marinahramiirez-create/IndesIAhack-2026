"""Configuración del RAG de AIworkspaces."""

from pathlib import Path

# Carpeta raíz que se documenta (la carpeta padre de _rag)
WORKSPACE = Path(__file__).resolve().parent.parent

# Base vectorial persistente
CHROMA_DIR = Path(__file__).resolve().parent / "chroma_db"
COLLECTION = "aiworkspaces"

# Modelos de Ollama (descárgalos con `ollama pull <modelo>`)
LLM_MODEL = "llama3.2"            # modelo Llama para generar texto (alternativa: llama3.1:8b)
EMBED_MODEL = "nomic-embed-text"  # modelo de embeddings
NUM_CTX = 8192                    # ventana de contexto que se pide a Ollama

# Fragmentación y recuperación
CHUNK_SIZE = 1200          # caracteres por fragmento
CHUNK_OVERLAP = 200
TOP_K = 6                  # fragmentos recuperados por consulta
MAX_CONTEXT_CHARS = 18000  # contexto máximo enviado al LLM

# Qué se indexa
EXTENSIONS = {
    ".py", ".ipynb", ".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".csv", ".sql", ".r", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".java", ".c", ".cpp",
    ".h", ".cs", ".go", ".rs", ".sh", ".ps1", ".bat", ".pdf", ".docx",
}
MAX_FILE_BYTES = 5 * 1024 * 1024  # ignora archivos > 5 MB

IGNORED_DIRS = {
    "_rag", ".git", ".venv", "venv", "env", "__pycache__", "node_modules", ".ipynb_checkpoints",
    ".idea", ".vscode", "dist", "build", "chroma_db",
    # agentic_os_plantilla: plugin de Obsidian (1,3 MB de JS ajeno), copia duplicada de
    # skills/agentes (_instalar) y papelera: solo meterían ruido en las búsquedas
    ".obsidian", "_instalar", "_papelera",
}

# Archivos que genera este sistema (no se reindexan para no retroalimentarse)
DOC_FILENAME = "DOCUMENTACION.md"
GENERATED_FILES = {DOC_FILENAME, "DOCUMENTACION_GENERAL.md"}
