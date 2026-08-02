"""Slice 1: render, nav, zoom. One page at a time, rendered via PyMuPDF."""
import fitz  # PyMuPDF
from PIL import Image

DEFAULT_ZOOM = 1.5  # 108 DPI-equivalent at PyMuPDF's 72-DPI base


def detect_content_bbox(doc: fitz.Document, sample_pages=None, padding: float = 8.0) -> "fitz.Rect | None":
    """Real content bounding box (union of text + images + vector
    drawings) across a SAMPLE of pages, not per-page. One shared crop
    rect for the whole document, not a per-page-varying one: most real
    PDFs have uniform margins page to page, and a single shared rect
    keeps layout.py's uniform-column-width assumption intact.

    Sampling (not just page 0): a document whose first page is a title
    page with less content than the rest would otherwise get a
    too-tight crop applied everywhere, clipping real content on later
    pages. Unions across the sample instead -- the smallest rect that's
    still safe for every sampled page, at the cost of being looser than
    a true per-page crop on any page that needs less than the sample's
    max extent.

    Returns None (caller's cue to skip cropping entirely) when nothing
    detectable exists on any sampled page -- a real, non-error case
    (blank pages, pure-background scans with no OCR text layer) rather
    than a false-positive near-zero rect that would crop away real
    (undetectable-to-this-method) content."""
    if sample_pages is None:
        n = doc.page_count
        # First/middle/last plus a couple more, capped -- enough to catch
        # a title-page-is-different pattern without scanning huge docs.
        sample_pages = sorted(set(min(n - 1, i) for i in (0, 1, n // 2, n - 2, n - 1) if i >= 0))
    union = None
    for i in sample_pages:
        page = doc[i]
        boxes = [fitz.Rect(b[:4]) for b in page.get_text("blocks")]
        boxes += [fitz.Rect(img["bbox"]) for img in page.get_image_info()]
        for d in page.get_drawings():
            r = d.get("rect")
            if r is not None:
                boxes.append(fitz.Rect(r))
        for b in boxes:
            if b.is_empty or b.is_infinite:
                continue
            union = b if union is None else union | b
    if union is None:
        return None
    page_rect = doc[sample_pages[0]].rect
    union = fitz.Rect(
        union.x0 - padding, union.y0 - padding,
        union.x1 + padding, union.y1 + padding,
    )
    # Clamp to the real page bounds -- padding must never push the crop
    # rect outside the page itself.
    union = union & page_rect
    return union if not union.is_empty else None


class Viewer:
    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self.page_num = 0
        self.zoom = DEFAULT_ZOOM

    @property
    def page_count(self):
        return self.doc.page_count

    def render_page(self, page_num=None, zoom=None, clip=None) -> Image.Image:
        """Render one page to a PIL Image at the given zoom (1.0 = 72 DPI).

        get_pixmap() with no explicit alpha/colorspace args already
        produces raw RGB samples -- frombytes() is zero-copy interop
        vs. round-tripping through a PNG compress/decompress cycle
        (Image.open(BytesIO(pix.tobytes("png")))), same pixels, no
        waste.

        clip: an optional fitz.Rect in PAGE space (pre-zoom, same
        convention as detect_content_bbox's return value) -- get_pixmap's
        own `clip` param renders ONLY that sub-rectangle, at the SAME
        zoom, rather than rendering the full page and cropping
        afterward (cheaper, and matches layout.py's crop_rect-aware
        geometry which expects the rendered image's real pixel size to
        match the cropped rect, not the full page)."""
        page_num = self.page_num if page_num is None else page_num
        zoom = self.zoom if zoom is None else zoom
        page = self.doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img

    def next_page(self):
        if self.page_num < self.page_count - 1:
            self.page_num += 1
        return self.page_num

    def prev_page(self):
        if self.page_num > 0:
            self.page_num -= 1
        return self.page_num

    def goto(self, page_num):
        self.page_num = max(0, min(self.page_count - 1, page_num))
        return self.page_num

    def zoom_in(self, step=0.25):
        self.zoom += step
        return self.zoom

    def zoom_out(self, step=0.25, floor=0.25):
        self.zoom = max(floor, self.zoom - step)
        return self.zoom

    def fit_width(self, viewport_width: float, page_num=None, floor=0.25, ceiling=8.0,
                  content_width=None):
        """Set zoom so the current (or given) page's width exactly fills
        viewport_width -- pages wider than DEFAULT_ZOOM's fixed 1.5x
        (e.g. a landscape diagram PDF) would otherwise open at literal
        1:1-ish size and run off-screen. Clamped to the same practical
        range zoom_in/zoom_out allow (floor stops a degenerate near-zero
        zoom on a very wide page; ceiling stops a tiny page from
        zooming absurdly large).

        content_width: without this, Fit Width always measures the
        page's FULL native width even with crop_to_content on, so the
        cropped content floats smaller inside the same frame instead of
        the freed-up margin space being used as extra zoom. Callers
        that know the active crop rect's width pass it here (None ->
        real native page width, unchanged behavior when crop is off)."""
        page_num = self.page_num if page_num is None else page_num
        native_width = content_width if content_width is not None else self.doc[page_num].rect.width
        if native_width <= 0:
            return self.zoom  # degenerate page geometry -- leave zoom untouched
        self.zoom = max(floor, min(ceiling, viewport_width / native_width))
        return self.zoom

    def get_outline(self) -> list:
        """(level, title, page_num) for the document's real embedded
        outline/bookmarks (PyMuPDF's `get_toc()`) -- a separate thing
        from any visual "Table of Contents" page the document might
        also have as regular text. `get_toc()`'s page numbers are
        1-indexed; converted here to the 0-indexed `page_num` the rest
        of this class already uses, confirmed directly (not assumed) via
        a controlled `set_toc`/`get_toc` round-trip. No outline at all
        is a real, common, non-error case -- returns an empty list, the
        caller (UI) is responsible for showing that plainly rather than
        an empty-looking panel."""
        return [(level, title, page - 1) for level, title, page in self.doc.get_toc()]
