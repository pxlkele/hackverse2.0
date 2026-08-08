"""
Retrieval over the Chroma index built by ingestion/pipeline.py.

Important: RAG here supplies *citations*, not answers. The rule engine decides
eligibility; this module's job is to find the government text that proves each
rule is real.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import chromadb

from .llm import embed
from .schemas import Citation, RetrievedChunk

CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION = "setu_schemes"


@lru_cache(maxsize=1)
def _collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def search(
    query: str, k: int = 5, scheme_id: str | None = None
) -> list[RetrievedChunk]:
    """Semantic search, optionally scoped to one scheme."""
    collection = _collection()
    if collection.count() == 0:
        return []

    where = {"scheme_id": scheme_id} if scheme_id else None
    results = collection.query(
        query_embeddings=[embed(query)],
        n_results=min(k, collection.count()),
        where=where,
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    chunks: list[RetrievedChunk] = []
    for i, chunk_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                text=results["documents"][0][i],
                source_doc=meta.get("source_doc", ""),
                scheme_id=meta.get("scheme_id", ""),
                scheme_name=meta.get("scheme_name", ""),
                page_no=int(meta.get("page_no", 0)),
                heading=meta.get("heading", ""),
                distance=float(results["distances"][0][i]),
            )
        )
    return chunks


def cite(query: str, scheme_id: str | None = None, max_chars: int = 320) -> Citation | None:
    """Best single supporting passage for a claim, trimmed to a quotable span."""
    hits = search(query, k=1, scheme_id=scheme_id)
    if not hits:
        return None

    hit = hits[0]
    snippet = hit.text
    if len(snippet) > max_chars:
        # Prefer cutting at a sentence boundary so the quote reads cleanly.
        cut = snippet.rfind(". ", 0, max_chars)
        snippet = snippet[: cut + 1] if cut > max_chars // 2 else snippet[:max_chars] + "..."

    return Citation(
        source_doc=hit.source_doc,
        page_no=hit.page_no,
        heading=hit.heading,
        snippet=snippet.strip(),
    )


def stats() -> dict:
    collection = _collection()
    if collection.count() == 0:
        return {"chunks": 0, "schemes": [], "documents": []}

    everything = collection.get()
    metas = everything["metadatas"]
    return {
        "chunks": collection.count(),
        "schemes": sorted({m.get("scheme_id", "") for m in metas}),
        "documents": sorted({m.get("source_doc", "") for m in metas}),
    }
