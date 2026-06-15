"""
Script para poblar la base de datos vectorial de Jarvis.
Uso:
    python3 knowledge.py add "xxx es el creador de Jarvis y vive en Monterrey"
    python3 knowledge.py add-file notas.txt
    python3 knowledge.py list
    python3 knowledge.py delete <id>
    python3 knowledge.py clear
    python3 knowledge.py search "¿quién creó Jarvis?"
"""

import sys
import os
from pathlib import Path
from jarvis.src.ai.rag import db, embedding_fn, COLLECTION_NAME
import chromadb
import uuid

# ─────────────────────────────────────────
# Comandos
# ─────────────────────────────────────────

def cmd_add(text: str):
    doc_id = str(uuid.uuid4())[:8]
    db.add(
        documents=[text],
        ids=[doc_id],
    )
    print(f"✅ Agregado [{doc_id}]: {text[:80]}{'...' if len(text) > 80 else ''}")

def cmd_add_file(path: str):
    content = Path(path).read_text(encoding="utf-8").strip()
    # Dividir en párrafos para mejor granularidad
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for para in paragraphs:
        cmd_add(para)
    print(f"✅ {len(paragraphs)} fragmentos agregados desde {path}")

def cmd_list():
    result = db.get()
    if not result["documents"]:
        print("📭 La base de conocimiento está vacía.")
        return
    print(f"📚 {len(result['documents'])} documentos:\n")
    for doc_id, doc in zip(result["ids"], result["documents"]):
        print(f"  [{doc_id}] {doc[:100]}{'...' if len(doc) > 100 else ''}")

def cmd_delete(doc_id: str):
    db.delete(ids=[doc_id])
    print(f"🗑️  Eliminado: {doc_id}")

def cmd_clear():
    confirm = input("⚠️  ¿Borrar toda la base de conocimiento? (s/n): ")
    if confirm.lower() == "s":
        result = db.get()
        if result["ids"]:
            db.delete(ids=result["ids"])
        print("🧹 Base de conocimiento limpiada.")

def cmd_search(query: str):
    results = db.query(query_texts=[query], n_results=3)
    print(f"🔍 Resultados para: '{query}'\n")
    for doc_id, doc, distance in zip(
        results["ids"][0],
        results["documents"][0],
        results["distances"][0],
    ):
        relevance = 1 - distance
        print(f"  [{doc_id}] (relevancia: {relevance:.2f})")
        print(f"  {doc}\n")

# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 3:
        cmd_add(" ".join(sys.argv[2:]))
    elif cmd == "add-file" and len(sys.argv) == 3:
        cmd_add_file(sys.argv[2])
    elif cmd == "list":
        cmd_list()
    elif cmd == "delete" and len(sys.argv) == 3:
        cmd_delete(sys.argv[2])
    elif cmd == "clear":
        cmd_clear()
    elif cmd == "search" and len(sys.argv) >= 3:
        cmd_search(" ".join(sys.argv[2:]))
    else:
        print(__doc__)