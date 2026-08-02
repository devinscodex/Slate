"""One open document's state -- one Tab per notebook tab in slate.py.

Plain data holder, no behavior of its own. SlateApp saves/loads a Tab's
mutable fields (mode, page, pending_redactions, search_state) into its
own flat self.doc/self.path/self.viewer/etc attributes around every tab
switch -- every existing single-document method (render, save, redact,
sign, search, ...) keeps reading those same flat attributes completely
unchanged, unaware tabs exist at all. path/doc/viewer never change
after a Tab is created, so only the other four fields need saving back.
"""
import fitz

import search
from viewer import Viewer


class Tab:
    def __init__(self, path: str, doc: fitz.Document, viewer: Viewer):
        self.path = path
        self.doc = doc
        self.viewer = viewer
        self.page = doc[0]
        self.mode = "view"
        self.pending_redactions = []  # [(page_num, fitz.Rect), ...]
        self.search_state = search.SearchState()
