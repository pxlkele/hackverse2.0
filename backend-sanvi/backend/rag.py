"""
Setu - RAG + Granite reasoning layer.

Retrieves grounded scheme chunks from Chroma, then asks Granite (via the
Hugging Face Inference API) to reason over ONLY that retrieved context and
produce a plain-language, cited eligibility answer.

This is the module to get rock-solid before touching voice. Test it from the
command line first:

    export HF_TOKEN=...
    python backend/rag.py "I run a tailoring shop, no loan history"
"""
import os
import chromadb
from sentence_transformers import SentenceTransformer
from huggingface_hub import InferenceClient

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
COLLECTION_NAME = "setu_schemes"
EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# NOTE: confirm this exact model id is servable on your HF Inference API tier
# before demo day - swap via GRANITE_MODEL env var if it 404s. Fall back to a
# Hugging Face Inference Endpoint (dedicated) if the serverless API rate-limits.
GRANITE_MODEL = os.environ.get("GRANITE_MODEL", "ibm-granite/granite-3.1-8b-instruct")
HF_TOKEN = os.environ.get("HF_TOKEN")
TOP_K = int(os.environ.get("RAG_TOP_K", 4))

_embedder = None
_collection = None
_hf_client = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=DB_DIR)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def _get_hf_client():
    global _hf_client
    if _hf_client is None:
        if not HF_TOKEN:
            raise RuntimeError("HF_TOKEN not set. Put it in .env or export it before running.")
        _hf_client = InferenceClient(model=GRANITE_MODEL, token=HF_TOKEN)
    return _hf_client


def retrieve(query: str, top_k: int = TOP_K):
    embedder = _get_embedder()
    collection = _get_collection()
    query_embedding = embedder.encode([query]).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=top_k)

    hits = []
    if not results["documents"] or not results["documents"][0]:
        return hits
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        hits.append({"text": doc, "source": meta.get("source"), "distance": dist})
    return hits


def list_indexed_sources():
    """All distinct source filenames currently indexed in Chroma. Used by the
    dashboard's re-match view to show what's in the knowledge base vs. what a
    given user has already been matched to."""
    collection = _get_collection()
    data = collection.get()
    metadatas = data.get("metadatas") or []
    return sorted({m.get("source") for m in metadatas if m and m.get("source")})


PROMPT_TEMPLATE = """You are Setu, an assistant that helps low-literacy, vernacular-speaking users in India \
discover government schemes, microloans, and insurance they are eligible for.

Rules:
- Only use the CONTEXT below. If the context doesn't support an answer, say you don't have enough \
verified information yet - never invent scheme details, amounts, or deadlines.
- Explain eligibility in plain, simple language (write as if speaking aloud, not as a legal document).
- Always cite which source document each claim comes from.
- List any documents the user would need to apply.

CONTEXT:
{context}

USER SITUATION:
{query}

Respond in this exact format:
1. Plain-language eligibility explanation
2. Matched scheme(s) with source citation
3. Required documents checklist
4. Confidence: [High/Medium/Low] based on how directly the context supports this match
"""


def answer(query: str, top_k: int = TOP_K):
    hits = retrieve(query, top_k=top_k)
    if not hits:
        return {
            "answer": "No matching scheme found in the verified knowledge base yet. "
            "Confidence: [Low]",
            "sources": [],
            "hits": [],
        }

    context = "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)
    prompt = PROMPT_TEMPLATE.format(context=context, query=query)

    client = _get_hf_client()
    response = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.2,
    )
    text = response.choices[0].message.content

    return {
        "answer": text,
        "sources": sorted({h["source"] for h in hits}),
        "hits": hits,
    }


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "I run a tailoring shop, no loan history"
    result = answer(q)
    print(result["answer"])
    print("\nSources:", result["sources"])
