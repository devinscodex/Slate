"""Slice 4 check: add one of each annotation type, reload, enumerate
page.annots(), confirm type/rect/contents."""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import annotate  # noqa: E402


def _rect_close(a: fitz.Rect, b: fitz.Rect, tol=5):
    """PyMuPDF nudges annotation rects slightly (stroke width, quad
    padding) -- compare with a small pixel tolerance, not exact equality."""
    return (
        abs(a.x0 - b.x0) <= tol
        and abs(a.y0 - b.y0) <= tol
        and abs(a.x1 - b.x1) <= tol
        and abs(a.y1 - b.y1) <= tol
    )


def test_one_of_each_annotation_type_persists(tmp_path):
    path = str(tmp_path / "annotated.pdf")
    doc = fitz.open()
    page = doc.new_page()

    highlight_rect = fitz.Rect(72, 72, 200, 90)
    freetext_rect = fitz.Rect(72, 100, 300, 140)
    rect_shape = fitz.Rect(72, 200, 150, 250)
    stamp_rect = fitz.Rect(72, 260, 200, 300)
    ink_strokes = [[(72, 150), (100, 180), (130, 150)]]

    annotate.add_highlight(page, highlight_rect)
    annotate.add_freetext(page, freetext_rect, "hello note")
    annotate.add_ink(page, ink_strokes)
    annotate.add_rect_shape(page, rect_shape)
    annotate.add_stamp(page, stamp_rect)

    doc.save(path)
    doc.close()

    reread = fitz.open(path)
    page2 = reread[0]
    annots = list(page2.annots())
    assert len(annots) == 5

    by_type = {a.type[1]: a for a in annots}
    assert set(by_type) == {"Highlight", "FreeText", "Ink", "Square", "Stamp"}

    assert _rect_close(by_type["Highlight"].rect, highlight_rect)
    assert _rect_close(by_type["FreeText"].rect, freetext_rect)
    assert by_type["FreeText"].info.get("content") == "hello note"
    assert _rect_close(by_type["Square"].rect, rect_shape, tol=3)
    assert _rect_close(by_type["Stamp"].rect, stamp_rect)
    assert by_type["Stamp"].info.get("content") == "Approved"
    # Ink's rect is the bounding box PyMuPDF computed from the stroke
    # points, not a rect we specified -- just confirm it's non-empty and
    # roughly where the stroke was drawn.
    ink_rect = by_type["Ink"].rect
    assert not ink_rect.is_empty
    assert ink_rect.x0 < 140 and ink_rect.y1 > 140

    reread.close()


def test_highlight_is_translucent_not_opaque(tmp_path):
    """add_highlight's default opacity must be meaningfully translucent
    (<=0.5), not PyMuPDF's own default of fully opaque -- MuPDF's pixmap
    rasterizer doesn't reliably honor the Multiply blend mode Highlight
    annots are spec'd to use, so a fully-opaque highlight renders as a
    solid block over the text instead of a translucent mark."""
    path = str(tmp_path / "translucent.pdf")
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(72, 72, 200, 90)

    annotate.add_highlight(page, rect)
    doc.save(path)
    doc.close()

    reread = fitz.open(path)
    annot = next(a for a in reread[0].annots() if a.type[1] == "Highlight")
    assert annot.opacity <= 0.5
    reread.close()


def test_highlight_accepts_custom_color_and_opacity(tmp_path):
    """Callers (slate.py's _highlight_selection) pass the active theme's
    real highlight_bg color -- confirm a non-default color/opacity
    actually lands on the saved annotation, not just the hardcoded
    default."""
    path = str(tmp_path / "custom_color.pdf")
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(72, 72, 200, 90)

    annotate.add_highlight(page, rect, color=(0.2, 0.6, 0.2), opacity=0.4)
    doc.save(path)
    doc.close()

    reread = fitz.open(path)
    annot = next(a for a in reread[0].annots() if a.type[1] == "Highlight")
    assert abs(annot.opacity - 0.4) < 0.02
    stroke = annot.colors.get("stroke")
    assert stroke is not None
    assert abs(stroke[0] - 0.2) < 0.02
    assert abs(stroke[1] - 0.6) < 0.02
    assert abs(stroke[2] - 0.2) < 0.02
    reread.close()
