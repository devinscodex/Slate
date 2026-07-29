"""Slice 2 (Fable design review, 2026-07-25): canvas-space geometry for
stacking multiple rendered pages in continuous-scroll mode. Pure math
only -- no Tk, no fitz.Page objects held onto past construction.
Deliberately kept separate from Viewer (viewer.py): Viewer's
page_num/render_page()/next_page() contract is exactly what
single-page mode still needs unchanged, and multi-page canvas layout
is a different concern (Tk-canvas geometry, not document state).

Built fresh whenever page count or zoom changes; never touched by
scrolling itself (scrolling only moves the canvas viewport over this
already-computed geometry).

`cols` (Fable design review, 2026-07-25, Slice 3 perf consult): added
now as groundwork for Slice 4's side-by-side view, even though every
caller today still uses the cols=1 default -- row-major grid with
cols=1 collapses to exactly the same vertical-list geometry as before,
so this costs nothing for the current slice and means Slice 4 never
has to touch this class's core math again. Every column shares one
fixed width (the widest page in the whole document) rather than a
per-column width -- same "left-align first pass, revisit only if it
looks wrong live" simplicity already established for mixed page
sizes."""
import fitz


class PageLayout:
    def __init__(self, doc: fitz.Document, zoom: float, gap: int = 2, cols: int = 1,
                 center_offset_x: float = 0.0, crop_rect: "fitz.Rect | None" = None):
        """center_offset_x (Devin, 2026-07-29 -- "current default alignment
        isn't centered"): a single horizontal shift applied to every rect,
        computed by the caller (slate.py knows the real Tk canvas viewport
        width; this class deliberately stays Tk-free, pure math only, per
        its own module docstring) as max(0, (viewport_width - content_width)
        / 2). Baking it in HERE, once, means every existing call site that
        already trusts rect_of()'s coordinates for drawing, click hit-
        testing (page_at), TTS highlight placement, and text-selection
        overlays all get centered positions automatically -- no separate
        offset-plumbing needed at each of those call sites. Zero when
        content is already >= viewport width (nothing to center, the
        existing left-pinned behavior IS correct once real horizontal
        scrolling is needed).

        crop_rect (Devin, 2026-07-29 -- "build the crop feature... don't
        like big page margins"): ONE shared crop rectangle (in page-space,
        pre-zoom), from viewer.detect_content_bbox(), applied uniformly to
        EVERY page rather than a per-page-varying crop. Deliberately
        uniform: real PDFs almost always share the same margins page to
        page, and a single shared rect means col_w/row_heights below stay
        exactly the "widest page in the doc" math already established --
        no per-page-varying-dimensions complexity rippling through the
        side-by-side/continuous layout geometry for what's fundamentally a
        cosmetic feature. The caller (slate.py) is responsible for
        actually rendering each page's pixmap clipped to this same rect
        (get_pixmap(clip=crop_rect)) so the drawn image size matches what
        this class computes here -- this class only does the geometry."""
        self.zoom = zoom
        self.gap = gap
        self.cols = cols
        self.center_offset_x = center_offset_x  # public: staleness checks compare against this directly
        self.crop_rect = crop_rect  # public: staleness checks compare against this directly
        self._rects = []  # [(page_num, x0, y0, x1, y1), ...] canvas px
        if crop_rect is not None:
            page_dims = [(crop_rect.width * zoom, crop_rect.height * zoom) for _ in range(doc.page_count)]
        else:
            page_dims = [(doc[i].rect.width * zoom, doc[i].rect.height * zoom) for i in range(doc.page_count)]
        col_w = max((w for w, _h in page_dims), default=0.0)
        row_heights = []
        for row_start in range(0, len(page_dims), cols):
            row = page_dims[row_start:row_start + cols]
            row_heights.append(max(h for _w, h in row) if row else 0.0)
        for i, (w, h) in enumerate(page_dims):
            row, col = divmod(i, cols)
            x0 = center_offset_x + col * (col_w + gap)
            row_y = sum(row_heights[:row]) + row * gap
            self._rects.append((i, x0, row_y, x0 + w, row_y + h))
        self._total_h = sum(row_heights) + max(0, len(row_heights) - 1) * gap
        # content_width: the real, UN-shifted document width -- callers
        # (slate.py) need this to compute next render's center_offset_x
        # without it compounding the previous pass's own offset.
        self.content_width = cols * col_w + max(0, cols - 1) * gap
        self._total_w = center_offset_x + self.content_width

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

    def pages_in_range(self, top_y: float, bottom_y: float) -> list:
        """Every page whose rect vertically overlaps [top_y, bottom_y]
        -- the real basis for windowed rendering (Fable design review,
        2026-07-25, Slice 3): callers pass the viewport's own bounds
        expanded by one screenful of slack, so "how many pages" falls
        naturally out of zoom/viewport size instead of a tuned
        page-count constant."""
        return [
            page_num for page_num, _x0, y0, _x1, y1 in self._rects
            if y1 >= top_y and y0 <= bottom_y
        ]

    @property
    def total_size(self) -> tuple:
        return self._total_w, self._total_h
