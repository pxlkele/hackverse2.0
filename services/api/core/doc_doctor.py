"""
Document Doctor — catch the rejection before it happens.

A name spelled one way on an Aadhaar card and another way on a bank passbook is
one of the quietest ways an application dies: the form goes in, months pass,
nothing happens, and nobody tells the applicant why. They conclude the scheme
was never meant for people like them.

This reads the documents a person actually holds, extracts the identity fields,
and compares them against each other *before* anything is submitted.

Two extraction paths, same fallback discipline as the rest of the system:
    granite3.2-vision  if the model is present (better on cards and photos)
    Docling OCR        otherwise — no extra download, works offline

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


def _extract_with_vision(image_path: Path) -> dict[str, Any]:
    import base64

    encoded = base64.b64encode(image_path.read_bytes()).decode()
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": VISION_MODEL,
                "messages": [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": "Read this document and return its fields as JSON.",
                        "images": [encoded],
                    },
                ],
                "stream": False,
                "format": EXTRACT_SCHEMA,
                "options": {"temperature": 0.0},
            },
        )
        response.raise_for_status()
        return json.loads(response.json()["message"]["content"])


def _ocr_text(image_path: Path) -> str:
    """Docling OCR. Slower than a vision model but needs no extra download."""
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(image_path))
    return " ".join(result.document.export_to_markdown().split())


def extract(image_path: str | Path, doc_type_hint: str | None = None) -> ExtractedDoc:
    """Read one document. Falls back from vision to OCR rather than failing."""
    path = Path(image_path)

    if vision_available():
        try:
            data = _extract_with_vision(path)
            return ExtractedDoc(
                doc_type=doc_type_hint or data.get("doc_type") or "unknown",
                name=data.get("name"),
                dob=data.get("dob"),
                address=data.get("address"),
                father_or_spouse=data.get("father_or_spouse"),
                source_file=path.name,
                extraction_method=VISION_MODEL,
            )
        except Exception:
            pass  # fall through to OCR

    text = _ocr_text(path)
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
        extraction_method="docling-ocr + granite",
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

    paths: [(image_path, doc_type_hint | None), ...]
    """
    docs = [extract(p, hint) for p, hint in paths]
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
        "summary": (
            "No problems found — these documents are consistent."
            if not blockers
            else f"{len(blockers)} problem(s) that would likely cause a rejection."
        ),
    }
