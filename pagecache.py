"""Windowed page-image cache for continuous scroll. Without it,
_render_continuous() would re-rasterize every page on every render()
call (navigation, zoom, theme change); this caches only pages near the
current viewport ("the window"), lazily filling new ones and evicting
stale ones, so a render/scroll only touches a handful of pages
regardless of document length.

Separate from PageLayout (pure math, no Tk/fitz.Page state) since this
class exists specifically to hold Tk PhotoImage state across render()
calls. Owned by SlateApp as a single long-lived instance
(self._page_cache), not reconstructed per render."""


class PageImageCache:
    def __init__(self, make_image_fn):
        """make_image_fn(page_num) -> ImageTk.PhotoImage -- the real,
        possibly-expensive render+colorize+wrap. Called only on a
        cache miss (first time a page enters the window)."""
        self._make_image_fn = make_image_fn
        self._images = {}  # page_num -> PhotoImage, window members only

    def get(self, page_num):
        img = self._images.get(page_num)
        if img is None:
            img = self._make_image_fn(page_num)
            self._images[page_num] = img
        return img

    def has(self, page_num) -> bool:
        return page_num in self._images

    def set_window(self, page_nums) -> None:
        """Evict anything outside the new window -- keeps the cache's
        real memory/PhotoImage-handle cost bounded to "one screenful of
        slack," not "every page in the document." Cheap to call on
        every scroll tick: a dict-key diff, not a re-render."""
        wanted = set(page_nums)
        for p in list(self._images):
            if p not in wanted:
                del self._images[p]

    def invalidate_all(self) -> None:
        """Zoom or theme change: every cached pixel is wrong (zoom
        changes page dimensions outright; theme colorize is baked into
        the stored PhotoImage at fill-time, not reapplied per-draw, so
        a theme switch is a full cache bust too -- an accepted
        tradeoff, not an oversight)."""
        self._images.clear()
