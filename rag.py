"""
Módulo RAG — inicializa ChromaDB con embeddings via Ollama y expone la función de búsqueda.
Importado por server.py y knowledge.py.
"""

import logging
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────

DB_PATH         = "./knowledge_db"
COLLECTION_NAME = "jarvis_knowledge"
OLLAMA_HOST     = "http://172.27.80.1:11434"
EMBED_MODEL     = "nomic-embed-text"  # ollama pull nomic-embed-text
TOP_K           = 3
MIN_RELEVANCE   = 0.3

# ─────────────────────────────────────────
# Inicialización (se ejecuta al importar)
# ─────────────────────────────────────────

log.info("⏳ Inicializando RAG...")

embedding_fn = OllamaEmbeddingFunction(
    model_name=EMBED_MODEL,
    url=f"{OLLAMA_HOST}/api/embeddings",
)

_client = chromadb.PersistentClient(path=DB_PATH)
db = _client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=embedding_fn,
    metadata={"hnsw:space": "cosine"},
)

log.info(f"✅ RAG listo — {db.count()} documentos en la base.")


# ─────────────────────────────────────────
# Búsqueda
# ─────────────────────────────────────────

def search(query: str) -> str:
    """
    Busca fragmentos relevantes para la query.
    Retorna un string con el contexto listo para inyectar en el prompt,
    o string vacío si no hay nada relevante.
    """
    if db.count() == 0:
        return ""

    results = db.query(query_texts=[query], n_results=min(TOP_K, db.count()))

    fragments = []
    for doc, distance in zip(results["documents"][0], results["distances"][0]):
        relevance = 1 - distance
        if relevance >= MIN_RELEVANCE:
            fragments.append(doc)

    if not fragments:
        return ""

    context = "\n".join(f"- {f}" for f in fragments)
    log.info(f"🔍 RAG: {len(fragments)} fragmentos relevantes encontrados.")
    return context