"""Document converters for common office tasks (PDF <-> Markdown/text/
images). Zero new dependencies -- reuses PyMuPDF, already a dependency.

`pymupdf4llm` (the obvious off-the-shelf choice for PDF->Markdown)
pulls `pymupdf-layout` (a 41MB wheel) plus a full ONNX Runtime, numpy,
protobuf, networkx -- 80MB+ of transitive weight for a layout-detection
ML model. Too much weight for what this needs; `pdf_to_markdown` below
is hand-rolled instead, using the same span-level text data
(size/flags) `textedit.py` already parses for font info.
"""
import os
import shutil
import subprocess
import tempfile

import fitz

# PyMuPDF span flags (same bitfield textedit.py already decodes).
_FLAG_BOLD = 16

# Candidate Chromium-family browser paths for html_to_pdf's headless
# print-to-pdf. PyMuPDF/fitz cannot render HTML+CSS+JS itself (it's a
# PDF engine, not a browser) -- real rendering (charts, dark-mode CSS,
# the dataviz skill's output) needs an actual browser engine. Reusing
# an already-installed Chromium-family browser in --headless mode is
# zero new Python dependencies, same "compose from what's already
# here" doctrine as the rest of this module -- the alternative
# (weasyprint/pdfkit-class libraries) is a real new dependency tree for
# something already on disk.
_BROWSER_CANDIDATES = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _wsl_mount_variant(win_path: str) -> str | None:
    """`C:\\Program Files\\...` -> `/mnt/c/Program Files/...`, so the
    same candidate list resolves under WSL's own Python too, not just a
    native Windows one. `os.path.exists` on a raw Windows path is
    unconditionally False under WSL, so `_find_browser` would otherwise
    always fall through to `shutil.which` (which also fails -- brave.exe
    isn't on a WSL shell's PATH). Checking both forms unconditionally is
    cheap and keeps this list correct from either venv without branching
    on platform."""
    if len(win_path) < 3 or win_path[1] != ":":
        return None
    drive = win_path[0].lower()
    rest = win_path[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def _find_browser() -> str:
    for path in _BROWSER_CANDIDATES:
        if os.path.exists(path):
            return path
        wsl_path = _wsl_mount_variant(path)
        if wsl_path and os.path.exists(wsl_path):
            return wsl_path
    found = shutil.which("brave.exe") or shutil.which("chrome.exe")
    if found:
        return found
    raise FileNotFoundError(
        "No Chromium-family browser found (checked Brave/Chrome standard "
        "install paths -- both native and WSL-mounted forms -- and PATH) "
        "-- html_to_pdf needs one for real HTML+CSS+JS rendering."
    )


def html_to_pdf(html_path: str, pdf_path: str, timeout: int = 30) -> str:
    """Renders an HTML file to PDF via a real browser engine's own
    --headless --print-to-pdf, not a hand-rolled HTML parser -- the
    only way to get real CSS (incl. the dataviz skill's light/dark
    handling) and any inline JS-rendered content (charts) to actually
    render, matching what a human would see opening it directly.

    Gotcha: --headless mode's print-to-pdf ignores @media print rules
    some pages might rely on and instead prints the on-screen
    (@media screen) layout -- worth knowing if an HTML source assumes
    print CSS applies.
    """
    browser = _find_browser()
    abspath = os.path.abspath(html_path)
    result = subprocess.run(
        [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            abspath,
        ],
        capture_output=True,
        timeout=timeout,
    )
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
        raise RuntimeError(
            f"html_to_pdf: no output produced (browser exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:500]}"
        )
    return pdf_path


def path_to_pdf(path: str) -> str:
    """Dispatches by extension to the right converter, returning a path
    to a real PDF ready for Slate's own viewer -- one entry point so
    callers (slate.py's _open_document) don't need per-format logic.
    Writes to a temp file; caller owns cleanup, same convention as
    epubfix.fix_epub_encoding_conflicts's corrected-copy approach."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".html", ".htm"):
        fd, out = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        return html_to_pdf(path, out)
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".heic"):
        fd, out = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        doc = images_to_pdf([path])
        doc.save(out)
        doc.close()
        return out
    return path  # PDF, epub, txt, md (plain-text render) -- already native


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
                # otherwise tie on "most frequent size" -- body text is
                # reliably the size with the most total characters.
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
    documented technique: Document.convert_to_pdf()) and inserted."""
    out = fitz.open()
    for path in image_paths:
        img_doc = fitz.open(path)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        img_pdf = fitz.open("pdf", pdf_bytes)
        out.insert_pdf(img_pdf)
        img_pdf.close()
    return out
