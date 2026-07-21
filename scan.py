"""Scan for financial/PII-shaped content (bank account/routing numbers,
SSNs, credit card numbers) -- helps decide what needs redacting. Started
as a one-off scratch audit script, promoted to a real feature.

Scope, stated plainly rather than implied: this catches specific
NUMBER-SHAPED patterns only (SSN, ABA routing, labeled account numbers,
Luhn-valid card numbers). It does NOT catch general PII (a name, phone
number, or address with no account-shaped context), business-confidential
content, or anything in an image-only/scanned PDF with no text layer --
same OCR gap DESIGN.md already names as out of v1 for redaction itself.
A page with 0 extracted characters is flagged as UNSCANNABLE rather than
silently reported clean, specifically because this bit a real file
during development (Sage-PDF-Converter-Permissions.pdf, an image-only
PDF that produced a false "nothing found" before this check existed).
"""
import re

import fitz

SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
ROUTING_LABEL = re.compile(r"(?:ABA|Routing)", re.I)
ACCOUNT_LABEL = re.compile(r"Account\s*(?:Number|No\.?|#)", re.I)
BARE_9_DIGIT = re.compile(r"^\D*(\d{9})\D*$")
BARE_ACCOUNT_DIGITS = re.compile(r"^\D*(\d{6,17})\D*$")
CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits]
    checksum = 0
    for i, val in enumerate(reversed(d)):
        if i % 2 == 1:
            val *= 2
            if val > 9:
                val -= 9
        checksum += val
    return checksum % 10 == 0


def _next_nonblank(lines, start, window=4):
    """Real PDF text extraction often puts a label and its value on
    SEPARATE lines -- confirmed directly against a real bank letter
    ('Account Number:' / blank / '9825039777', each its own line). A
    same-line-only regex silently missed this (a real false-negative
    caught during development, not a hypothetical) -- look forward a
    few non-blank lines instead of just the current one."""
    found = 0
    for j in range(start, min(start + window, len(lines))):
        if lines[j].strip():
            found += 1
            yield j, lines[j]
            if found >= 2:  # label line itself + up to one value line
                return


def scan_page_text(text: str):
    """Returns a list of (line_index, kind, matched_value, context)."""
    hits = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if SSN.search(line):
            m = SSN.search(line)
            hits.append((idx, "ssn", m.group(), line.strip()[:100]))
        for m in CARD_CANDIDATE.finditer(line):
            digits = re.sub(r"[ -]", "", m.group())
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                hits.append((idx, "card-number", m.group().strip(), line.strip()[:100]))
        if ROUTING_LABEL.search(line):
            for j, cand in _next_nonblank(lines, idx + 1):
                m = BARE_9_DIGIT.match(cand)
                if m:
                    hits.append((j, "routing-number", m.group(1), f"{line.strip()[:50]} -> {cand.strip()}"))
        if ACCOUNT_LABEL.search(line):
            for j, cand in _next_nonblank(lines, idx + 1):
                m = BARE_ACCOUNT_DIGITS.match(cand)
                if m:
                    hits.append((j, "account-number", m.group(1), f"{line.strip()[:50]} -> {cand.strip()}"))
    return hits


def scan_document(doc: fitz.Document):
    """Returns a list of dicts: {page, kind, value, rect, context}.
    `rect` is a fitz.Rect if the matched value could be located back on
    the page (via search_for), else None -- callers (e.g. the UI's
    "mark for redaction" action) should handle a missing rect instead
    of assuming one always exists. A page that extracts 0 characters
    is reported as its own {"page": n, "kind": "unscannable", ...} entry
    rather than silently producing zero hits -- an image-only page is
    NOT the same claim as "checked, nothing sensitive found"."""
    results = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        text = page.get_text()
        if not text.strip():
            results.append(
                {
                    "page": page_num,
                    "kind": "unscannable",
                    "value": None,
                    "rect": None,
                    "context": "page has no extractable text (image-only? needs OCR, out of v1)",
                }
            )
            continue
        for _lineidx, kind, value, context in scan_page_text(text):
            rect = None
            found = page.search_for(value)
            if found:
                rect = found[0]
            results.append(
                {"page": page_num, "kind": kind, "value": value, "rect": rect, "context": context}
            )
    return results


def scan_directory(dir_path: str, pattern="*.pdf"):
    """Batch mode: the real Downloads-folder-audit use case. Returns
    {filename: [scan_document results]} for every PDF with at least one
    hit (including unscannable pages) -- files with nothing found at
    all are omitted, matching the original audit script's behavior."""
    import pathlib

    root = pathlib.Path(dir_path)
    out = {}
    for p in sorted(root.glob(pattern)):
        try:
            doc = fitz.open(str(p))
        except Exception as e:
            out[p.name] = [{"page": None, "kind": "could-not-open", "value": None, "rect": None, "context": str(e)}]
            continue
        hits = scan_document(doc)
        doc.close()
        if hits:
            out[p.name] = hits
    return out
