"""
Verify every citation in schemes.yaml against the actual PDF.

The product's central claim is that any decision can be traced to a line of a
real government document. That claim is only worth something if the quotes are
genuinely there, on the page we say they are. This checks it mechanically.

    .venv/bin/python eval/verify_citations.py

Note on matching: PDF text extraction inserts spurious spaces mid-word
("account holder s", "Street  Vendor"), so comparison strips whitespace and
punctuation entirely and matches on the remaining character stream.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pypdf
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "ingestion" / "sources"
SCHEMES = ROOT / "services" / "api" / "data" / "schemes.yaml"

# How much of a quote must match. Quotes are lightly reflowed when written into
# YAML, and some are stitched from adjacent lines, so we probe a distinctive
# prefix rather than demanding the whole thing.
PROBE_CHARS = 60


def squash(text: str) -> str:
    """Lowercase, drop everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


_page_cache: dict[str, list[str] | None] = {}


def pages(doc: str) -> list[str] | None:
    if doc not in _page_cache:
        path = SOURCES / doc
        if not path.exists():
            _page_cache[doc] = None
        else:
            reader = pypdf.PdfReader(str(path))
            _page_cache[doc] = [squash(p.extract_text() or "") for p in reader.pages]
    return _page_cache[doc]


def citations() -> list[tuple[str, str, str, int | None, str]]:
    """(scheme_id, rule_id, doc, page, quote) for every citation in the file."""
    schemes = yaml.safe_load(open(SCHEMES))["schemes"]
    out = []
    for scheme in schemes:
        for rule in scheme["rules"]:
            doc = rule.get("source_doc")
            if rule.get("source_quote"):
                out.append((scheme["id"], rule["id"], doc,
                            rule.get("source_page"), rule["source_quote"]))
            remedy = rule.get("remedy") or {}
            if remedy.get("source_quote"):
                # A remedy may cite a different document from its rule - the
                # Category C provision lives in the Loan Operations guidelines
                # while the rule it unblocks is defined in the Scheme guidelines.
                out.append((scheme["id"], f"{rule['id']}:remedy",
                            remedy.get("source_doc") or doc,
                            remedy.get("source_page"), remedy["source_quote"]))
    return out


def main() -> int:
    problems: list[str] = []
    page_fixes: list[tuple[str, str, int, int]] = []
    checked = 0

    for scheme_id, rule_id, doc, page, quote in citations():
        checked += 1

        if str(quote).strip().startswith("PENDING"):
            problems.append(f"PENDING     {rule_id}: placeholder quote still in place")
            continue

        page_texts = pages(doc)
        if page_texts is None:
            problems.append(f"NO FILE     {rule_id}: {doc} is not in ingestion/sources")
            continue

        probe = squash(quote)[:PROBE_CHARS]
        found_on = [i for i, text in enumerate(page_texts, 1) if probe and probe in text]

        if not found_on:
            problems.append(
                f"NOT FOUND   {rule_id}: quote does not appear in {doc}\n"
                f"            {str(quote)[:100]}..."
            )
        elif page and page not in found_on:
            page_fixes.append((rule_id, doc, page, found_on[0]))
            problems.append(
                f"WRONG PAGE  {rule_id}: cited p{page} in {doc}, actually on p{found_on[0]}"
            )

    print(f"\n  Verified {checked} citations against {len(_page_cache)} PDFs")
    print(f"  Problems: {len(problems)}\n")
    for p in problems:
        print("   ", p)

    if page_fixes:
        print("\n  Page corrections needed in schemes.yaml:")
        for rule_id, doc, cited, actual in page_fixes:
            print(f"    {rule_id}: source_page: {cited} -> {actual}")

    if not problems:
        print("  Every citation resolves to real text on the page it claims.\n")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
