"""Slice 2 (Fable design review, 2026-07-25): canvas-space geometry for
stacking multiple rendered pages in continuous-scroll mode. Pure math
only -- no Tk, no fitz.Page objects held onto past construction.
Deliberately kept separate from Viewer (viewer.py): Viewer's
page_num/render_page()/next_page() contract is exactly what
single-page mode still needs unchanged, and multi-page canvas layout
is a different concern (Tk-canvas geometry, not document state).

Built fresh whenever page count or zoom changes; never touched by
scrolling itself (scrolling only moves the canvas viewport over this
already-computed geometry)."""
import fitz


class PageLayout:
    def __init__(self, doc: fitz.Document, zoom: float, gap: int = 8):
        self.zoom = zoom
        self.gap = gap
        self._rects = []  # [(page_num, x0, y0, x1, y1), ...] canvas px, left-aligned
        y = 0.0
        max_w = 0.0
        for i in range(doc.page_count):
            pr = doc[i].rect
            w, h = pr.width * zoom, pr.height * zoom
            self._rects.append((i, 0.0, y, w, y + h))
            y += h + gap
            max_w = max(max_w, w)
        self._total_h = max(0.0, y - gap)
        self._total_w = max_w

    def rect_of(self, page_num: int) -> tuple:
        """(x0, y0, x1, y1) canvas-space bounds of one page."""
        return self._rects[page_num][1:]

    def all_rects(self) -> list:
        return list(self._rects)

    def page_at(self, cx: float, cy: float):
        """Which page's rect contains this canvas point -- None if the
        point falls in the inter-page gap/margin (a real, non-error
        case: a click there isn't a click on any page)."""
        for page_num, x0, y0, x1, y1 in self._rects:
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return page_num
        return None

    def topmost_visible(self, top_y: float) -> int:
        """The page whose top edge is at or above top_y and is the
        LAST such page -- i.e. the page currently at the viewport's
        top edge, for syncing viewer.page_num from scroll position."""
        best = 0
        for page_num, _x0, y0, _x1, _y1 in self._rects:
            if y0 <= top_y:
                best = page_num
            else:
                break
        return best

    @property
    def total_size(self) -> tuple:
        return self._total_w, self._total_h
