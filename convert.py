"""Document converters for common office tasks (PDF <-> Markdown/text/
images). Zero new dependencies -- reuses PyMuPDF, already a dependency,
the same "compose from what's already here" doctrine as the rest of
Slate.

Real finding, not assumed: `pymupdf4llm` (the obvious off-the-shelf
choice for PDF->Markdown) looked lightweight on PyPI ("minimal core:
PyMuPDF and PyMuPDF Layout") but its actual `pip install` pulls
`pymupdf-layout` (a 41MB wheel) plus a full ONNX Runtime, numpy,
protobuf, networkx -- 80MB+ of transitive weight for a layout-detection
ML model, confirmed by literally installing it and inspecting what
landed. Not suckless. Reverted; `pdf_to_markdown` below is hand-rolled
instead, using the same span-level text data (size/flags) `textedit.py`
already parses for font info.
"""
import os

import fitz

# PyMuPDF span flags (same bitfield textedit.py already decodes).
_FLAG_BOLD = 16


def pdf_to_markdown(doc: fitz.Document) -> str:
    """Heading level is inferred from font size relative to the
    document's own body-text size (the most frequent size overall) --
    not a fixed threshold, since a report's "normal" size varies doc to
    doc. Whole-line-bold text (not already a heading) gets **bold**;
    lines already starting with a bullet character are normalized to
    a real markdown "- " list item.
    """
    size_char_totals = {}
    lines_per_page = []
    for page in doc:
        page_lines = []
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                size = round(spans[0]["size"], 1)
                all_bold = all(s["flags"] & _FLAG_BOLD for s in spans)
                # Weighted by character volume, not line count: a single
                # short title line and a single short body line would
                # otherwise tie on "most frequent size" (a real case
                # caught writing this module's own integration test) --
                # body text is reliably the size with the most total
                # characters, even when line counts are close or equal.
                size_char_totals[size] = size_char_totals.get(size, 0) + len(text)
                page_lines.append((text, size, all_bold))
        lines_per_page.append(page_lines)

    if not size_char_totals:
        return ""

    body_size = max(size_char_totals, key=size_char_totals.get)
    heading_sizes = sorted((s for s in size_char_totals if s > body_size), reverse=True)
    heading_level = {s: min(i + 1, 6) for i, s in enumerate(heading_sizes)}

    out = []
    for page_lines in lines_per_page:
        for text, size, all_bold in page_lines:
            level = heading_level.get(size)
            if level:
                out.append(f"{'#' * level} {text}")
            elif text[0] in "•‣◦" or text[:2] in ("- ", "* "):
                item = text[1:].strip() if text[0] in "•‣◦-*" else text
                out.append(f"- {item}")
            elif all_bold:
                out.append(f"**{text}**")
            else:
                out.append(text)
        out.append("")  # blank line between pages
    return "\n".join(out).strip() + "\n"


def pdf_to_text(doc: fitz.Document) -> str:
    """Plain text, one page's text per block, form-feed-separated --
    the same separator PyMuPDF's own get_text() convention implies
    between pages, explicit here since callers write this straight to
    a .txt file."""
    return "\f".join(page.get_text() for page in doc)


def pdf_to_images(doc: fitz.Document, out_dir: str, base_name: str, dpi: int = 150) -> list:
    """One PNG per page, {base_name}_p{N}.png, at the given DPI (not
    tied to the viewer's on-screen zoom -- a real print/email-ready
    resolution by default). Returns the written paths, in page order."""
    os.makedirs(out_dir, exist_ok=True)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    written = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        path = os.path.join(out_dir, f"{base_name}_p{i + 1}.png")
        pix.save(path)
        written.append(path)
    return written


def images_to_pdf(image_paths: list) -> fitz.Document:
    """One full-page-image per input file, in the given order. Each
    image is converted to its own one-page PDF first (PyMuPDF's own
    documented technique: Document.convert_to_pdf()) and inserted --
    confirmed live before writing this, not assumed."""
    out = fitz.open()
    for path in image_paths:
        img_doc = fitz.open(path)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        img_pdf = fitz.open("pdf", pdf_bytes)
        out.insert_pdf(img_pdf)
        img_pdf.close()
    return out
