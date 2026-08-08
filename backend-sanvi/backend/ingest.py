"""
Setu - Document ingestion pipeline.

Reads scheme documents (PDF/TXT) from data/schemes/, cleans + chunks them,
embeds them, and stores them in a persistent Chroma collection.

This is the "Data Prep Kit + Docling -> knowledge base" step in the
architecture: everything downstream (RAG, Granite reasoning) is only ever
grounded in what gets indexed here. Garbage in here = hallucinated eligibility
advice out. Only put verified government scheme PDFs / circulars in
data/schemes/.

Usage:
    python backend/ingest.py
"""
import os
import glob
import chromadb
from sentence_transformers import SentenceTransformer

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "schemes")
DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
COLLECTION_NAME = "setu_schemes"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def extract_text(path: str) -> str:
    """Extract text from a scheme document. Tries Docling first (better
    structure-aware parsing of govt PDFs/tables), falls back to pypdf,
    falls back to plain text read."""
    if path.lower().endswith(".pdf"):
        try:
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(path)
            return result.document.export_to_markdown()
        except Exception as e:
            print(f"[ingest] Docling failed for {path} ({e}), falling back to pypdf")
            try:
                from pypdf import PdfReader
                reader = PdfReader(path)
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as e2:
                print(f"[ingest] pypdf also failed for {path}: {e2}")
                return ""
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c.strip() for c in chunks if c.strip()]


def main():
    os.makedirs(DB_DIR, exist_ok=True)
    files = [f for f in glob.glob(os.path.join(DATA_DIR, "*")) if os.path.isfile(f)]
    if not files:
        print(f"[ingest] No files found in {DATA_DIR}. Add scheme PDFs/TXT there first.")
        return

    print(f"[ingest] Loading embedding model: {EMBED_MODEL_NAME}")
    embedder = SentenceTransformer(EMBED_MODEL_NAME)

    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_or_create_collection(COLLECTION_NAME)

    ids, docs, metadatas = [], [], []
    for path in files:
        fname = os.path.basename(path)
        print(f"[ingest] Processing {fname}")
        text = extract_text(path)
        if not text.strip():
            print(f"[ingest]   WARNING: no text extracted from {fname}")
            continue
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            ids.append(f"{fname}::{i}")
            docs.append(chunk)
            metadatas.append({"source": fname, "chunk_index": i})

    if not docs:
        print("[ingest] Nothing to index.")
        return

    print(f"[ingest] Embedding {len(docs)} chunks...")
    embeddings = embedder.encode(docs, show_progress_bar=True).tolist()

    collection.upsert(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings)
    print(f"[ingest] Indexed {len(docs)} chunks from {len(files)} files into '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    main()
