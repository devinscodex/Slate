"""Slice 1: render, nav, zoom. One page at a time, rendered via PyMuPDF."""
import fitz  # PyMuPDF
from PIL import Image

DEFAULT_ZOOM = 1.5  # 108 DPI-equivalent at PyMuPDF's 72-DPI base


class Viewer:
    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self.page_num = 0
        self.zoom = DEFAULT_ZOOM

    @property
    def page_count(self):
        return self.doc.page_count

    def render_page(self, page_num=None, zoom=None) -> Image.Image:
        """Render one page to a PIL Image at the given zoom (1.0 = 72 DPI).

        Real perf fix (Fable design review, 2026-07-25, after Devin hit
        a live lockup): get_pixmap() with no explicit alpha/colorspace
        args already produces raw RGB samples -- the original
        `Image.open(BytesIO(pix.tobytes("png")))` was a full PNG
        COMPRESS (in PyMuPDF/C) followed by a full PNG DECOMPRESS (in
        PIL) on every single call, pure waste. frombytes() is the
        standard zero-copy interop instead -- behavior-identical
        pixels, no round-trip. Speeds up every render in every mode,
        not just continuous-scroll's eager-render loop."""
        page_num = self.page_num if page_num is None else page_num
        zoom = self.zoom if zoom is None else zoom
        page = self.doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
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

    def fit_width(self, viewport_width: float, page_num=None, floor=0.25, ceiling=8.0):
        """Set zoom so the current (or given) page's native width exactly
        fills viewport_width. Fixes a real bug (Devin, 2026-07-26): pages
        wider than DEFAULT_ZOOM's fixed 1.5x (e.g. a landscape diagram
        PDF) opened at literal 1:1-ish size and ran off-screen -- every
        document should default to fitting the view, not a fixed zoom
        that only happens to work for common page sizes. Clamped to the
        same practical range zoom_in/zoom_out already allow (floor stops
        a degenerate near-zero zoom on a very wide page; ceiling stops a
        tiny page from zooming absurdly large)."""
        page_num = self.page_num if page_num is None else page_num
        native_width = self.doc[page_num].rect.width
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
