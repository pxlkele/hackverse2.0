"""
Document Doctor — catch the rejection before it happens.

A name spelled one way on an Aadhaar card and another way on a bank passbook is
one of the quietest ways an application dies: the form goes in, months pass,
nothing happens, and nobody tells the applicant why. They conclude the scheme
was never meant for people like them.

This reads the documents a person actually holds, extracts the identity fields,
and compares them against each other *before* anything is submitted.

Two stages, because each model is good at a different thing:
    granite3.2-vision  reads the pixels and returns prose
    granite4:tiny-h    turns that prose into typed fields

Constraining the vision model to a JSON schema made it hang past a two-minute
timeout, so it transcribes and the text model structures.

Docling OCR is the fallback, and only the fallback. Measured on the same cards,
OCR read "RAMESH H KUMAR" off one printed "RAMESH KUMAR" and dropped another
name entirely — a doubling artifact invents a mismatch that isn't there, and a
dropped name hides one that is. Both failures are worse than useless for a
feature whose whole job is comparing spellings, so a reading that fell back to
OCR is flagged as unreliable rather than reported as fact.

Nothing here decides eligibility. It reports what differs and how badly.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .llm import OLLAMA_URL, TIMEOUT, chat_json

VISION_MODEL = "granite3.2-vision"

# Honorifics and relational prefixes that appear on Indian documents but are not
# part of the legal name. "S/O" and "W/O" especially — a passbook often carries
# the father's or husband's name in the same field.
_TITLES = re.compile(
    r"\b(shri|sri|smt|mrs|mr|ms|kum|km|late|s/o|d/o|w/o|c/o|son of|daughter of|wife of)\b\.?",
    re.IGNORECASE,
)
_NON_NAME = re.compile(r"[^A-Za-zऀ-ॿ\s]")

DOC_LABELS = {
    "aadhaar": "Aadhaar card",
    "bank_passbook": "bank passbook",
    "voter_id": "voter ID",
    "pan": "PAN card",
    "ration_card": "ration card",
    "vending_certificate": "vending certificate",
}


@dataclass
class ExtractedDoc:
    """What we could read off one document."""

    doc_type: str
    name: str | None = None
    dob: str | None = None
    address: str | None = None
    father_or_spouse: str | None = None
    source_file: str = ""
    raw_text: str = ""
    extraction_method: str = ""


@dataclass
class Finding:
    """One problem, and what it would have cost."""

    severity: str          # blocker | warning | info
    field_name: str
    message: str
    values: dict[str, str] = field(default_factory=dict)
    consequence: str = ""
    fix: str = ""


# ── name comparison ──────────────────────────────────────────────────────────

def normalise_name(name: str) -> str:
    """Strip titles, punctuation and spacing so only the name itself remains."""
    cleaned = _TITLES.sub(" ", name or "")
    cleaned = _NON_NAME.sub(" ", cleaned)
    return " ".join(cleaned.upper().split())


def _token_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def compare_names(a: str, b: str) -> tuple[str, float, str]:
    """
    Returns (verdict, similarity, explanation).

    verdict is one of: match, reordered, initial, spelling, mismatch

    The distinction matters. A spelling variant is a real blocker that the
    applicant can fix in an hour at a bank. Genuinely different names mean we
    are probably looking at two different people's documents, which is a
    different conversation entirely.
    """
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return "mismatch", 0.0, "one of the names could not be read"

    if na == nb:
        return "match", 1.0, "identical"

    ta, tb = na.split(), nb.split()

    if sorted(ta) == sorted(tb):
        return "reordered", 0.95, "same words in a different order"

    # Abbreviation, which is extremely common on passbooks: "RAMESH KUMAR" and
    # "R KUMAR", or a middle name reduced to an initial. Treated separately from
    # a misspelling because the fix and the risk are different.
    def initials(tokens: list[str]) -> str:
        return "".join(tok[0] for tok in tokens)

    if len(ta) == len(tb):
        abbreviated = [
            (x, y) for x, y in zip(ta, tb)
            if (len(x) == 1 or len(y) == 1) and x[0] == y[0] and x != y
        ]
        rest_matches = all(
            x == y for x, y in zip(ta, tb)
            if not ((len(x) == 1 or len(y) == 1) and x[0] == y[0])
        )
        if abbreviated and rest_matches:
            pairs = ", ".join(f"{x} vs {y}" for x, y in abbreviated)
            return "initial", 0.9, f"one document abbreviates part of the name: {pairs}"

    if len(ta) != len(tb) and (initials(ta) == initials(tb) or set(ta) <= set(tb) or set(tb) <= set(ta)):
        return "initial", 0.85, "one document abbreviates or omits part of the name"

    ratio = _token_similarity(na, nb)

    # Same number of parts, and each part is close but not equal: a spelling
    # variant, e.g. KUMAR vs KUMAAR.
    if len(ta) == len(tb):
        per_token = [_token_similarity(x, y) for x, y in zip(ta, tb)]
        if all(r >= 0.7 for r in per_token) and any(r < 1.0 for r in per_token):
            differing = [
                f"{x} vs {y}" for x, y, r in zip(ta, tb, per_token) if r < 1.0
            ]
            return "spelling", ratio, "spelt differently: " + ", ".join(differing)

    if ratio >= 0.85:
        return "spelling", ratio, "spelt differently"

    return "mismatch", ratio, "these look like different names"


# ── extraction ───────────────────────────────────────────────────────────────

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "doc_type": {
            "type": "string",
            "enum": list(DOC_LABELS) + ["unknown"],
        },
        "name": {"type": ["string", "null"]},
        "dob": {"type": ["string", "null"]},
        "address": {"type": ["string", "null"]},
        "father_or_spouse": {"type": ["string", "null"]},
    },
    "required": ["doc_type"],
}

EXTRACT_SYSTEM = """You read Indian identity documents and return the fields exactly as printed.

- Copy the name EXACTLY as written, including any unusual spelling. Do not correct it. The spelling is the thing we are checking.
- name is the document holder. If the card also shows a father's, husband's or guardian's name (S/O, W/O, D/O), put that in father_or_spouse instead.
- dob as printed, DD/MM/YYYY where possible.
- Never invent a field. Use null if it is not visible.
- NEVER output an Aadhaar, PAN or account number."""


def vision_available() -> bool:
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
            tags = client.get(f"{OLLAMA_URL}/api/tags").json()
        return any(m["name"].startswith(VISION_MODEL) for m in tags.get("models", []))
    except Exception:
        return False


# Phone photographs are enormous and vision latency scales with pixels. 1600px
# on the long edge is plenty to read a printed name and keeps a card under a
# second of encoding.
MAX_EDGE = 1600

# The model needs to stay resident: loading 2.4GB per request turned a 3.5s
# inference into a 120s timeout, which then fell through to OCR and took 170s
# in total.
KEEP_ALIVE = "30m"


def _downscale(image_path: Path) -> bytes:
    """Shrink to MAX_EDGE, returning the original bytes if PIL can't open it."""
    try:
        import io

        from PIL import Image

        with Image.open(image_path) as img:
            img = img.convert("RGB")
            if max(img.size) > MAX_EDGE:
                ratio = MAX_EDGE / max(img.size)
                img = img.resize(
                    (int(img.width * ratio), int(img.height * ratio)),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=88)
            return buffer.getvalue()
    except Exception:
        return image_path.read_bytes()


def _transcribe_with_vision(image_path: Path) -> str:
    """
    Granite Vision reads the pixels and returns prose, not JSON.

    Constraining it to a JSON schema made the call hang past a two-minute
    timeout — a vision model doing constrained decoding is a bad trade. Let it
    do what it is good at (reading), and let the text model do what it is good
    at (structuring). Vision ~3.5s warm, structuring ~2s.
    """
    import base64

    encoded = base64.b64encode(_downscale(image_path)).decode()
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": VISION_MODEL,
                "keep_alive": KEEP_ALIVE,
                "stream": False,
                "options": {"temperature": 0.0},
                "messages": [{
                    "role": "user",
                    "content": (
                        "Transcribe every line of text visible on this document, "
                        "exactly as printed. Preserve the spelling exactly, even "
                        "if a word looks misspelt. Do not summarise or correct."
                    ),
                    "images": [encoded],
                }],
            },
        )
        response.raise_for_status()
        text = response.json()["message"]["content"]

    # It wraps output in <doc>...</doc>.
    return re.sub(r"</?doc>", " ", text).strip()


def warm() -> None:
    """
    Load the vision model before the first upload.

    Cold start is ~47s and warm inference ~3.5s. Someone standing at a desk
    with a vendor should not pay the difference.
    """
    if not vision_available():
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0)) as client:
            client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": VISION_MODEL, "keep_alive": KEEP_ALIVE, "stream": False,
                    "messages": [{"role": "user", "content": "ok"}],
                },
            )
    except Exception:
        pass


def _ocr_text(image_path: Path) -> str:
    """Docling OCR. Slower than a vision model but needs no extra download."""
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(image_path))
    return " ".join(result.document.export_to_markdown().split())


def extract(image_path: str | Path, doc_type_hint: str | None = None) -> ExtractedDoc:
    """
    Read one document: transcribe the pixels, then structure the text.

    Vision is tried first and Docling OCR is the fallback. A failure in either
    is recorded on the result rather than swallowed — a silent fallback meant we
    ran the slow path for days without noticing the fast one was broken.
    """
    path = Path(image_path)
    text = ""
    method = ""
    note = ""

    if vision_available():
        try:
            text = _transcribe_with_vision(path)
            method = VISION_MODEL
        except Exception as exc:  # noqa: BLE001
            note = f"vision failed ({type(exc).__name__}), used OCR"

    if not text.strip():
        text = _ocr_text(path)
        method = f"{method or 'docling-ocr'} + docling-ocr" if method else "docling-ocr"

    data = chat_json(
        prompt=f"Fields from this document text:\n\n{text[:3000]}",
        schema=EXTRACT_SCHEMA,
        system=EXTRACT_SYSTEM,
    )
    return ExtractedDoc(
        doc_type=doc_type_hint or data.get("doc_type") or "unknown",
        name=data.get("name"),
        dob=data.get("dob"),
        address=data.get("address"),
        father_or_spouse=data.get("father_or_spouse"),
        source_file=path.name,
        raw_text=text[:1000],
        extraction_method=f"{method} + granite" + (f" ({note})" if note else ""),
    )


# ── the check ────────────────────────────────────────────────────────────────

def check(docs: list[ExtractedDoc]) -> list[Finding]:
    """Cross-compare documents and report what would cause a rejection."""
    findings: list[Finding] = []

    named = [d for d in docs if d.name]
    if len(named) < 2:
        if len(docs) >= 2:
            findings.append(Finding(
                severity="warning",
                field_name="name",
                message="Could not read the name from every document.",
                consequence="We cannot confirm the names match.",
                fix="Retake the photo in better light, with the whole card in frame.",
            ))
        return findings

    for i, a in enumerate(named):
        for b in named[i + 1:]:
            verdict, ratio, why = compare_names(a.name, b.name)
            label_a = DOC_LABELS.get(a.doc_type, a.doc_type)
            label_b = DOC_LABELS.get(b.doc_type, b.doc_type)

            if verdict == "match":
                continue

            if verdict in ("spelling", "initial", "reordered"):
                findings.append(Finding(
                    severity="blocker",
                    field_name="name",
                    message=f"Your name is written differently on your {label_a} and your {label_b} — {why}.",
                    values={label_a: a.name, label_b: b.name},
                    consequence=(
                        "Applications are routinely rejected for this, often months later, "
                        "and usually without telling you the reason."
                    ),
                    fix=(
                        "Get one document corrected so both match exactly. A bank name "
                        "correction is free and usually same-day; an Aadhaar update can "
                        "be done at any Aadhaar Seva Kendra."
                    ),
                ))
            else:
                findings.append(Finding(
                    severity="blocker",
                    field_name="name",
                    message=f"The name on your {label_a} and your {label_b} do not appear to be the same person.",
                    values={label_a: a.name, label_b: b.name},
                    consequence="This will be rejected at verification.",
                    fix="Check you have photographed your own documents, not a family member's.",
                ))

    dobs = {d.doc_type: d.dob for d in docs if d.dob}
    if len(set(dobs.values())) > 1:
        findings.append(Finding(
            severity="blocker",
            field_name="dob",
            message="Your date of birth differs between documents.",
            values={DOC_LABELS.get(k, k): v for k, v in dobs.items()},
            consequence="Age-based schemes such as PMSBY will reject this.",
            fix="Get the incorrect document updated so both show the same date.",
        ))

    return findings


def review(paths: list[tuple[str | Path, str | None]]) -> dict[str, Any]:
    """
    Full pass: read every document, compare, report.

    Transcription and structuring are batched by model. Ollama evicts one model
    to load another, so interleaving vision and text calls per document paid a
    ~45s reload every time; doing all the reading first and all the structuring
    second costs one swap instead of one per document.

    paths: [(image_path, doc_type_hint | None), ...]
    """
    transcripts: list[tuple[Path, str | None, str, str]] = []

    # Pass 1 — vision reads every document while it is resident.
    for raw_path, hint in paths:
        path = Path(raw_path)
        text, method = "", ""
        if vision_available():
            try:
                text = _transcribe_with_vision(path)
                method = VISION_MODEL
            except Exception as exc:  # noqa: BLE001
                method = f"vision failed ({type(exc).__name__})"
        if not text.strip():
            text = _ocr_text(path)
            method = "docling-ocr" if not method else f"{method}, fell back to docling-ocr"
        transcripts.append((path, hint, text, method))

    # Pass 2 — the text model structures all of them.
    docs = []
    for path, hint, text, method in transcripts:
        data = chat_json(
            prompt=f"Fields from this document text:\n\n{text[:3000]}",
            schema=EXTRACT_SCHEMA,
            system=EXTRACT_SYSTEM,
        )
        docs.append(ExtractedDoc(
            doc_type=hint or data.get("doc_type") or "unknown",
            name=data.get("name"),
            dob=data.get("dob"),
            address=data.get("address"),
            father_or_spouse=data.get("father_or_spouse"),
            source_file=path.name,
            raw_text=text[:1000],
            extraction_method=f"{method} + granite",
        ))
    findings = check(docs)
    blockers = [f for f in findings if f.severity == "blocker"]

    return {
        "documents": [
            {
                "doc_type": d.doc_type,
                "label": DOC_LABELS.get(d.doc_type, d.doc_type),
                "name": d.name,
                "dob": d.dob,
                "source_file": d.source_file,
                "extraction_method": d.extraction_method,
            }
            for d in docs
        ],
        "findings": [
            {
                "severity": f.severity,
                "field": f.field_name,
                "message": f.message,
                "values": f.values,
                "consequence": f.consequence,
                "fix": f.fix,
            }
            for f in findings
        ],
        "clear": not blockers,
        # OCR mangles names in ways that matter here: it read "RAMESH H KUMAR"
        # off a card printed "RAMESH KUMAR", and dropped another name entirely.
        # A finding built on an OCR reading deserves a caveat.
        "reading_is_reliable": all(VISION_MODEL in d.extraction_method for d in docs),
        "summary": (
            "No problems found — these documents are consistent."
            if not blockers
            else f"{len(blockers)} problem(s) that would likely cause a rejection."
        ),
    }
