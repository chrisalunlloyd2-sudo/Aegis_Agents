import os
import time
from pathlib import Path
from gemini_bridge_rag import EnterpriseRAGSystem

def index_workspace():
    print("🚀 INIT: AEGIS MANIFOLD WORKSPACE INDEXER")

    try:
        rag = EnterpriseRAGSystem()
        if not rag.vector_client:
            print("❌ ERROR: Qdrant vector client failed to initialize. Check locks or installation.")
            return
    except Exception as e:
        print(f"❌ ERROR initializing RAG system: {e}")
        return

    valid_exts = {'.py', '.js', '.html', '.txt', '.md'}
    workspace_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    total_files = 0
    stored_chunks = 0

    for root, dirs, files in os.walk(workspace_dir):
        if '__pycache__' in root or '.git' in root or 'node_modules' in root:
            continue

        for file in files:
            ext = Path(file).suffix
            if ext in valid_exts:
                total_files += 1
                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Simple semantic chunking (2000 chars)
                    chunk_size = 2000
                    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

                    for idx, chunk in enumerate(chunks):
                        metadata = {
                            "filename": file,
                            "filepath": str(file_path.relative_to(workspace_dir)),
                            "chunk_index": idx,
                            "total_chunks": len(chunks)
                        }

                        success = rag.store_in_rag(
                            collection="gemini_files",
                            text=chunk,
                            metadata=metadata
                        )
                        if success:
                            stored_chunks += 1

                    print(f"✅ Indexed: {file} ({len(chunks)} chunks)")
                except Exception as e:
                    print(f"❌ Failed to index {file}: {e}")

    print("=========================================")
    print("🧠 RAG INDEXING COMPLETE")
    print(f"📁 Files Scanned: {total_files}")
    print(f"🧩 Chunks Vectorized: {stored_chunks}")
    print("=========================================")

if __name__ == "__main__":
    index_workspace()