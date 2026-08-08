"""
Setu ingestion pipeline.

    PDF -> Docling -> IBM Data Prep Kit chunking -> PII redact
        -> granite-embedding:278m -> Chroma

Every chunk keeps enough metadata to reconstruct a citation, because the whole
product rests on being able to point at the exact line of the exact government
document a decision came from.

Chunking uses DPK's doc_chunk transform (--chunker dpk, the default). It is
fast and returns richer provenance than hand-rolled splitting: real page
numbers, a JSON path into the document structure, and bounding boxes, which
means a citation can be traced to a region of a page rather than just a page.
--chunker builtin keeps the original heading-aware splitter as a fallback.

PII redaction stays regex-based rather than DPK's pii_redactor: that transform
loads flair/ner-english-large (~10 minutes to initialise) and is tuned for
English named entities, so it misses the Aadhaar and PAN formats that actually
appear in Indian government annexures.

Run:
    .venv/bin/python ingestion/pipeline.py
    .venv/bin/python ingestion/pipeline.py --rebuild
    .venv/bin/python ingestion/pipeline.py --chunker builtin
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import chromadb
import httpx
from docling.document_converter import DocumentConverter

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "ingestion" / "sources"
CHROMA_DIR = ROOT / "services" / "api" / "data" / "chroma"
MANIFEST = ROOT / "ingestion" / "manifest.json"

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "granite-embedding:278m"
COLLECTION = "setu_schemes"

# Chunking: big enough to carry a whole eligibility clause, small enough to cite.
TARGET_CHARS = 1200
OVERLAP_CHARS = 200

# Maps a source filename to the scheme it belongs to. Filenames are messy and
# come straight off government portals, so we match on substrings.
SCHEME_MAP = {
    "scheme guidelines": ("pm_svanidhi", "PM SVANidhi"),
    "loan operations": ("pm_svanidhi", "PM SVANidhi"),
    "street food hubs": ("pm_svanidhi", "PM SVANidhi"),
    "svanidhi": ("pm_svanidhi", "PM SVANidhi"),
    "fssai": ("fssai_basic", "FSSAI Basic Registration"),
    "eshram": ("e_shram", "e-Shram"),
    "e-shram": ("e_shram", "e-Shram"),
    "pmsby": ("pmsby", "PMSBY"),
    "suraksha": ("pmsby", "PMSBY"),
    "pmjjby": ("pmjjby", "PMJJBY"),
    "jeevan": ("pmjjby", "PMJJBY"),
    "vishwakarma": ("pm_vishwakarma", "PM Vishwakarma"),
}

# PII patterns. Government PDFs contain sample Aadhaar numbers, officer phone
# numbers and email addresses in annexures; none of that belongs in an index we
# ship publicly.
PII_PATTERNS = [
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR_REDACTED]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN_REDACTED]"),
    (re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b"), "[PHONE_REDACTED]"),
    (re.compile(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[EMAIL_REDACTED]"),
]


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_doc: str
    scheme_id: str
    scheme_name: str
    page_no: int
    heading: str
    chunk_index: int
    bbox: str = ""        # region on the page, from DPK - enables highlighting
    jsonpath: str = ""    # position in the document structure


def classify(filename: str) -> tuple[str, str]:
    """Best-effort map from a downloaded PDF name to a scheme."""
    low = filename.lower()
    for key, (sid, name) in SCHEME_MAP.items():
        if key in low:
            return sid, name
    return "unclassified", Path(filename).stem


def redact(text: str) -> str:
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def chunk_with_dpk(path: Path, source: str) -> list[Chunk]:
    """
    Chunk via IBM Data Prep Kit's doc_chunk transform.

    Docling produces the structured document; DPK splits it while preserving
    page number, bounding box and structural path for each piece.
    """
    import json as _json

    import pyarrow as pa
    from dpk_doc_chunk.transform import DocChunkTransform

    document = DocumentConverter().convert(str(path)).document
    transform = DocChunkTransform({"chunking_type": "dl_json"})

    table = pa.table({
        "contents": [_json.dumps(document.export_to_dict())],
        "document_id": [source],
    })
    out, _meta = transform.transform(table)

    scheme_id, scheme_name = classify(source)
    chunks: list[Chunk] = []

    for index, row in enumerate(out[0].to_pylist()):
        text = redact(" ".join(str(row.get("contents") or "").split()))
        if len(text) < 80:  # too short to be a useful citation
            continue

        try:
            page_no = int(row.get("page_number") or 0)
        except (TypeError, ValueError):
            page_no = 0

        digest = hashlib.sha1(f"{source}:{index}:{text[:64]}".encode()).hexdigest()[:16]
        chunks.append(
            Chunk(
                chunk_id=digest,
                text=text,
                source_doc=source,
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                page_no=page_no,
                heading="",
                chunk_index=index,
                bbox=str(row.get("bbox") or ""),
                jsonpath=str(row.get("doc_jsonpath") or ""),
            )
        )
    return chunks


def parse_pdf(path: Path) -> list[tuple[str, int, str]]:
    """Return (text, page_no, heading) triples from a PDF via Docling."""
    converter = DocumentConverter()
    result = converter.convert(str(path))
    doc = result.document

    blocks: list[tuple[str, int, str]] = []
    heading = ""

    for item, _level in doc.iterate_items():
        text = getattr(item, "text", "") or ""
        if not text.strip():
            continue

        label = str(getattr(item, "label", "")).lower()
        if "header" in label or "title" in label or "section" in label:
            heading = text.strip()
            continue

        page_no = 0
        provenance = getattr(item, "prov", None)
        if provenance:
            page_no = getattr(provenance[0], "page_no", 0) or 0

        blocks.append((text.strip(), page_no, heading))

    return blocks


def chunk_blocks(blocks: list[tuple[str, int, str]], source: str) -> list[Chunk]:
    """Group blocks into overlapping chunks, never merging across headings."""
    scheme_id, scheme_name = classify(source)
    chunks: list[Chunk] = []

    buffer: list[str] = []
    buf_len = 0
    cur_page = 0
    cur_heading = ""
    index = 0

    def flush() -> None:
        nonlocal buffer, buf_len, index
        if not buffer:
            return
        text = redact(" ".join(buffer).strip())
        if len(text) < 80:  # too short to be a useful citation
            buffer, buf_len = [], 0
            return
        digest = hashlib.sha1(f"{source}:{index}:{text[:64]}".encode()).hexdigest()[:16]
        chunks.append(
            Chunk(
                chunk_id=digest,
                text=text,
                source_doc=source,
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                page_no=cur_page,
                heading=cur_heading,
                chunk_index=index,
            )
        )
        index += 1
        # carry overlap so a clause split across a boundary is still retrievable
        tail = text[-OVERLAP_CHARS:] if len(text) > OVERLAP_CHARS else text
        buffer, buf_len = [tail], len(tail)

    for text, page_no, heading in blocks:
        if heading != cur_heading and buffer:
            flush()
            buffer, buf_len = [], 0
        cur_heading = heading
        cur_page = page_no or cur_page

        buffer.append(text)
        buf_len += len(text)
        if buf_len >= TARGET_CHARS:
            flush()

    buffer_had_content = bool(buffer)
    if buffer_had_content:
        flush()

    return chunks


# granite-embedding:278m has a 512-token window. DPK chunks follow document
# structure rather than a length budget, so a long table or clause list can
# exceed it and Ollama answers 500. Truncating for the *vector* is safe: the
# full text is still stored and still shown as the citation.
EMBED_CHAR_LIMIT = 1800


def embed(texts: list[str]) -> list[list[float]]:
    """
    Embed via Ollama. Sequential on purpose — this runs once, at build time.

    A chunk that cannot be embedded is skipped rather than aborting the run;
    losing one chunk is survivable, losing the whole index mid-build is not.
    """
    vectors: list[list[float] | None] = []
    failures = 0

    with httpx.Client(timeout=120.0) as client:
        for i, text in enumerate(texts, 1):
            payload = text[:EMBED_CHAR_LIMIT]
            try:
                response = client.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={"model": EMBED_MODEL, "prompt": payload},
                )
                response.raise_for_status()
                vectors.append(response.json()["embedding"])
            except Exception:
                # One more try, much shorter — usually enough.
                try:
                    response = client.post(
                        f"{OLLAMA_URL}/api/embeddings",
                        json={"model": EMBED_MODEL, "prompt": payload[:600]},
                    )
                    response.raise_for_status()
                    vectors.append(response.json()["embedding"])
                except Exception:
                    vectors.append(None)
                    failures += 1
            if i % 50 == 0:
                print(f"    embedded {i}/{len(texts)}")

    if failures:
        print(f"    ({failures} chunk(s) could not be embedded and were skipped)")
    return vectors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="wipe the index first")
    parser.add_argument(
        "--chunker", choices=["dpk", "builtin"], default="dpk",
        help="dpk = IBM Data Prep Kit doc_chunk (default); builtin = heading splitter",
    )
    args = parser.parse_args()

    pdfs = sorted(SOURCES_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {SOURCES_DIR}. Download the scheme guidelines first.")
        return 1

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if args.rebuild:
        try:
            client.delete_collection(COLLECTION)
            print("Wiped existing collection.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION, metadata={"hnsw:space": "cosine"}
    )

    all_chunks: list[Chunk] = []
    print(f"Chunker: {args.chunker}"
          + (" (IBM Data Prep Kit doc_chunk)" if args.chunker == "dpk" else ""))

    for pdf in pdfs:
        print(f"\n{pdf.name}")
        try:
            if args.chunker == "dpk":
                chunks = chunk_with_dpk(pdf, pdf.name)
            else:
                chunks = chunk_blocks(parse_pdf(pdf), pdf.name)
        except Exception as exc:
            print(f"  !! {args.chunker} chunking failed: {exc}")
            if args.chunker == "dpk":
                print("     falling back to builtin chunker")
                try:
                    chunks = chunk_blocks(parse_pdf(pdf), pdf.name)
                except Exception as exc2:
                    print(f"     builtin also failed: {exc2}")
                    continue
            else:
                continue
        scheme = chunks[0].scheme_name if chunks else "unclassified"
        print(f"  -> {len(chunks)} chunks  [{scheme}]")
        all_chunks.extend(chunks)

    if not all_chunks:
        print("\nNothing to index.")
        return 1

    existing = set(collection.get()["ids"]) if collection.count() else set()
    new_chunks = [c for c in all_chunks if c.chunk_id not in existing]
    if not new_chunks:
        print(f"\nIndex already current ({collection.count()} chunks).")
        return 0

    print(f"\nEmbedding {len(new_chunks)} new chunks with {EMBED_MODEL}...")
    vectors = embed([c.text for c in new_chunks])

    # Drop anything that failed to embed rather than inserting a null vector.
    paired = [(c, v) for c, v in zip(new_chunks, vectors) if v is not None]
    new_chunks = [c for c, _ in paired]
    vectors = [v for _, v in paired]

    collection.add(
        ids=[c.chunk_id for c in new_chunks],
        documents=[c.text for c in new_chunks],
        embeddings=vectors,
        metadatas=[
            {
                "source_doc": c.source_doc,
                "scheme_id": c.scheme_id,
                "scheme_name": c.scheme_name,
                "page_no": c.page_no,
                "heading": c.heading,
                "chunk_index": c.chunk_index,
                "bbox": c.bbox,
                "jsonpath": c.jsonpath,
            }
            for c in new_chunks
        ],
    )

    MANIFEST.write_text(
        json.dumps(
            {
                "total_chunks": collection.count(),
                "documents": sorted({c.source_doc for c in all_chunks}),
                "schemes": sorted({c.scheme_id for c in all_chunks}),
                "embed_model": EMBED_MODEL,
                "chunker": args.chunker,
            },
            indent=2,
        )
    )

    print(f"\nIndexed. Collection now holds {collection.count()} chunks.")
    print(f"Chroma: {CHROMA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
