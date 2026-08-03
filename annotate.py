"""Markup: highlight, freetext, ink, shapes, stamp. Thin wrappers over
PyMuPDF's own annotation API."""
import fitz


def add_highlight(page: fitz.Page, quad: fitz.Quad, color=(1, 0.85, 0), opacity=0.35) -> fitz.Annot:
    """PDF Highlight annotations are spec'd to render via Multiply blend
    mode, but MuPDF's own pixmap rasterizer (what Slate's viewer uses to
    display a page, and what reopening a saved PDF anywhere goes through)
    doesn't reliably honor blend modes in annotation appearance streams --
    the practical result of a bare add_highlight_annot() call is a solid
    opaque block instead of a translucent mark over the text. Real alpha
    (/CA via set_opacity) sidesteps the blend-mode gap entirely."""
    annot = page.add_highlight_annot(quad)
    annot.set_colors(stroke=color)
    annot.set_opacity(opacity)
    annot.update()
    return annot


def add_freetext(page: fitz.Page, rect: fitz.Rect, text: str, fontsize=12) -> fitz.Annot:
    return page.add_freetext_annot(rect, text, fontsize=fontsize)


def add_ink(page: fitz.Page, strokes: list) -> fitz.Annot:
    """strokes: list of polylines, each a list of (x, y) points."""
    return page.add_ink_annot(strokes)


def add_rect_shape(page: fitz.Page, rect: fitz.Rect) -> fitz.Annot:
    return page.add_rect_annot(rect)


def add_stamp(page: fitz.Page, rect: fitz.Rect, stamp_id=fitz.STAMP_Approved) -> fitz.Annot:
    return page.add_stamp_annot(rect, stamp_id)
