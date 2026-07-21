"""Redaction -- the highest-risk module (DESIGN.md). Genuinely removes
content, not just visually covers it. Every write here goes through
io_pdf.safe_save; there is no fast path.
"""
import fitz

import io_pdf

# images=1: remove ALL overlapping images entirely, not just blank pixels
# (PyMuPDF's own default, images=2, only blanks pixels -- not destructive
# enough for a "full redact" per DESIGN.md). graphics=2: remove ALL
# overlapping vector graphics, not just ones fully contained. text=0:
# remove text (already PyMuPDF's default).
FULL_REDACT_OPTIONS = dict(images=1, graphics=2, text=0)


def mark_region(page: fitz.Page, rect: fitz.Rect, label: str = ""):
    """Mark a rectangular region on a page for redaction. Nothing is
    removed until apply_all() runs."""
    page.add_redact_annot(rect, text=label if label else None, fill=(0, 0, 0))


def apply_all(doc: fitz.Document):
    """Apply every pending redaction annotation on every page, using the
    strongest destructive options (see FULL_REDACT_OPTIONS above)."""
    for page in doc:
        if page.first_annot is not None:
            page.apply_redactions(**FULL_REDACT_OPTIONS)


def strip_metadata(doc: fitz.Document):
    """Clear document metadata (XMP + info dict) as part of a full
    redact -- metadata is exactly the kind of place sensitive content
    can survive a content-stream-only redaction (DESIGN.md)."""
    doc.set_metadata({})
    if doc.xref_xml_metadata():
        doc.del_xml_metadata()


def redact_and_save(doc: fitz.Document, regions: list, out_path: str, label: str = ""):
    """High-level entry point: regions is a list of (page_num, fitz.Rect).
    Marks each region, applies all redactions, strips metadata, and
    writes out via the hardened safe_save path -- the only save path
    this function will ever use."""
    for page_num, rect in regions:
        mark_region(doc[page_num], rect, label=label)
    apply_all(doc)
    strip_metadata(doc)
    io_pdf.safe_save(doc, out_path)
