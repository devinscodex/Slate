"""OCR for image-only pages. Uses the Tesseract engine built into PyMuPDF;
only the language data (tessdata/*.traineddata) is needed at runtime.

The recognized words are written back as invisible text (render mode 3),
so the page keeps its original look and becomes searchable, selectable
and redactable like any text page."""
import os
from pathlib import Path

import fitz

TESSDATA_DIR = Path(__file__).parent / "tessdata"

# A page with fewer extractable characters than this counts as having no text.
MIN_TEXT_CHARS = 10


def tessdata_dir() -> str:
    """Bundled data directory, or TESSDATA_PREFIX when the bundle is absent."""
    if TESSDATA_DIR.is_dir():
        return str(TESSDATA_DIR)
    return os.environ.get("TESSDATA_PREFIX", "")


def available(language: str = "eng") -> bool:
    d = tessdata_dir()
    return bool(d) and all(
        os.path.exists(os.path.join(d, f"{lang}.traineddata"))
        for lang in language.split("+")
    )


def page_needs_ocr(page: fitz.Page) -> bool:
    """No usable text, but the page carries images to read."""
    if len(page.get_text().strip()) >= MIN_TEXT_CHARS:
        return False
    return bool(page.get_image_info())


def _latin1(word: str) -> str:
    return word.encode("latin-1", "ignore").decode("latin-1")


def _upright_copy(page: fitz.Page, dpi: int) -> fitz.Page:
    """The OCR engine ignores /Rotate, so read a render of the page as
    displayed. The temporary document is kept alive on the page copy."""
    tmp = fitz.open()
    copy = tmp.new_page(width=page.rect.width, height=page.rect.height)
    copy.insert_image(copy.rect, pixmap=page.get_pixmap(dpi=dpi))
    copy.parent_doc = tmp
    return copy


def ocr_page(page: fitz.Page, language: str = "eng", dpi: int = 300) -> int:
    """Add an invisible text layer to page. Returns the number of words."""
    src = _upright_copy(page, dpi) if page.rotation else page
    tp = src.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=tessdata_dir())
    words = src.get_text("words", textpage=tp)
    derot = page.derotation_matrix
    count = 0
    for x0, y0, x1, y1, word, *_ in words:
        word = _latin1(word)
        rect = fitz.Rect(x0, y0, x1, y1)
        if not word or rect.is_empty:
            continue
        size = max(rect.height * 0.8, 1)
        width = fitz.get_text_length(word, fontname="helv", fontsize=size)
        if width:
            size = min(max(size * rect.width / width, size * 0.5), size * 1.5)
        origin = fitz.Point(rect.x0, rect.y1 - rect.height * 0.2) * derot
        page.insert_text(
            origin, word, fontsize=size, fontname="helv",
            render_mode=3, rotate=page.rotation,
        )
        count += 1
    return count


def ocr_document(doc: fitz.Document, page_nums=None, language: str = "eng", dpi: int = 300, progress=None) -> dict:
    """OCR every listed page (default: all) that has no text. Returns
    {page_num: word_count} for the pages that were processed."""
    done = {}
    targets = range(doc.page_count) if page_nums is None else page_nums
    targets = [i for i in targets if page_needs_ocr(doc[i])]
    for n, i in enumerate(targets):
        if progress:
            progress(n, len(targets))
        done[i] = ocr_page(doc[i], language=language, dpi=dpi)
    if progress:
        progress(len(targets), len(targets))
    return done
