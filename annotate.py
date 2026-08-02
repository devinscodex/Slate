"""Markup: highlight, freetext, ink, shapes, stamp. Thin wrappers over
PyMuPDF's own annotation API."""
import fitz


def add_highlight(page: fitz.Page, quad: fitz.Quad) -> fitz.Annot:
    return page.add_highlight_annot(quad)


def add_freetext(page: fitz.Page, rect: fitz.Rect, text: str, fontsize=12) -> fitz.Annot:
    return page.add_freetext_annot(rect, text, fontsize=fontsize)


def add_ink(page: fitz.Page, strokes: list) -> fitz.Annot:
    """strokes: list of polylines, each a list of (x, y) points."""
    return page.add_ink_annot(strokes)


def add_rect_shape(page: fitz.Page, rect: fitz.Rect) -> fitz.Annot:
    return page.add_rect_annot(rect)


def add_stamp(page: fitz.Page, rect: fitz.Rect, stamp_id=fitz.STAMP_Approved) -> fitz.Annot:
    return page.add_stamp_annot(rect, stamp_id)
