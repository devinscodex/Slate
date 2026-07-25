"""Slice 3 perf fix (Fable design review, 2026-07-25), after Devin hit
a real lockup live: continuous-scroll's _render_continuous() was
eager-rendering EVERY page on EVERY render() call (every navigation,
every zoom notch, every theme change) -- PageUp/PageDown, which route
through render(), each re-rasterized the whole document and threw it
away a moment later. This cache holds only the pages near the current
viewport ("the window"), lazily filling new ones and evicting stale
ones, so a single render()/scroll only ever touches a handful of
pages regardless of document length.

Deliberately its own small module, not folded into PageLayout --
layout.py's own docstring already draws that line ("Pure math only --
no Tk, no fitz.Page objects held onto"); this class exists specifically
to hold Tk PhotoImage state across render() calls, which PageLayout is
not supposed to do. Owned by SlateApp as a single long-lived instance
(self._page_cache), not reconstructed per render -- its whole value is
surviving across calls."""


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
