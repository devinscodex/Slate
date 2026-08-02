"""In-document text search (Sumatra-style Find). PyMuPDF's own
page.search_for() is already case-insensitive (confirmed directly, not
assumed) -- no extra normalization needed. Real gotcha caught before
writing any tests: search_for("") returns None, not an empty list --
callers must guard the empty-query case explicitly or a naive `for
match in page.search_for(query)` crashes on a blank Find box.
"""
import fitz


def find_all_matches(doc: fitz.Document, query: str) -> list:
    """[(page_num, fitz.Rect), ...] across the whole document, in page
    order. Empty/whitespace-only query -> [], not an error."""
    if not query or not query.strip():
        return []
    matches = []
    for page_num in range(doc.page_count):
        for rect in doc[page_num].search_for(query):
            matches.append((page_num, rect))
    return matches


class SearchState:
    """Tracks the current match list and which one is "current" --
    the UI's next/prev (n/N) just calls advance()/retreat() and asks
    current() for where to jump, rather than re-deriving position from
    scratch on every keypress."""

    def __init__(self):
        self.query = ""
        self.matches = []  # [(page_num, fitz.Rect), ...]
        self.index = -1  # -1 == no current match (no search run yet, or 0 results)

    def run(self, doc: fitz.Document, query: str):
        self.query = query
        self.matches = find_all_matches(doc, query)
        self.index = 0 if self.matches else -1

    def current(self):
        if self.index < 0 or not self.matches:
            return None
        return self.matches[self.index]

    def advance(self):
        """Next match, wrapping around to the first past the last."""
        if not self.matches:
            return None
        self.index = (self.index + 1) % len(self.matches)
        return self.current()

    def retreat(self):
        """Previous match, wrapping around to the last before the first."""
        if not self.matches:
            return None
        self.index = (self.index - 1) % len(self.matches)
        return self.current()

    def matches_on_page(self, page_num: int) -> list:
        """Just the rects on one page -- what render() needs to draw
        highlight overlays without re-searching."""
        return [r for p, r in self.matches if p == page_num]
