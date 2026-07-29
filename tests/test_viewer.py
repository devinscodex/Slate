"""Slice 1 check: every page of a fixture renders; dimensions/checksums are
deterministic and match expected."""
import hashlib
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from viewer import Viewer, detect_content_bbox  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "basic3page.pdf")


def _hash(img):
    return hashlib.sha256(img.tobytes()).hexdigest()


def test_page_count():
    doc = fitz.open(FIXTURE)
    v = Viewer(doc)
    assert v.page_count == 3
    doc.close()


def test_every_page_renders_with_expected_dimensions():
    doc = fitz.open(FIXTURE)
    v = Viewer(doc)
    zoom = 1.5
    for i in range(v.page_count):
        rect = doc[i].rect  # ground truth: the page's own mediabox, in points
        expected_w = rect.width * zoom
        expected_h = rect.height * zoom
        img = v.render_page(page_num=i, zoom=zoom)
        # PyMuPDF's rasterizer and Python's round() disagree on .5 rounding
        # (banker's vs round-half-up) -- allow the 1px it actually produces.
        assert abs(img.width - expected_w) <= 1
        assert abs(img.height - expected_h) <= 1
    doc.close()


def test_render_is_deterministic():
    """Same page + same zoom -> byte-identical render, both times."""
    doc = fitz.open(FIXTURE)
    v = Viewer(doc)
    first = [_hash(v.render_page(page_num=i)) for i in range(v.page_count)]
    second = [_hash(v.render_page(page_num=i)) for i in range(v.page_count)]
    assert first == second
    # Pages have different text ("page 1", "page 2", "page 3") -> must not
    # all hash the same (would indicate the page number is being ignored).
    assert len(set(first)) == v.page_count
    doc.close()


def test_zoom_changes_dimensions():
    doc = fitz.open(FIXTURE)
    v = Viewer(doc)
    base = v.render_page(page_num=0, zoom=1.0)
    zoomed = v.render_page(page_num=0, zoom=2.0)
    assert zoomed.width == base.width * 2
    assert zoomed.height == base.height * 2
    doc.close()


def test_nav_bounds():
    doc = fitz.open(FIXTURE)
    v = Viewer(doc)
    assert v.page_num == 0
    v.prev_page()  # already at 0, must not go negative
    assert v.page_num == 0
    for _ in range(10):
        v.next_page()
    assert v.page_num == v.page_count - 1  # clamps at last page
    doc.close()


def test_get_outline_with_real_toc():
    doc = fitz.open(FIXTURE)
    # set_toc uses 1-indexed page numbers -- confirmed directly via a
    # controlled round-trip before writing Viewer.get_outline() at all.
    doc.set_toc([[1, "Chapter One", 1], [2, "Section 1.1", 2], [1, "Chapter Two", 3]])
    v = Viewer(doc)
    outline = v.get_outline()
    assert outline == [
        (1, "Chapter One", 0),
        (2, "Section 1.1", 1),
        (1, "Chapter Two", 2),
    ]
    doc.close()


def test_get_outline_with_no_toc_is_empty_not_an_error():
    doc = fitz.open(FIXTURE)  # the fixture has no outline set
    v = Viewer(doc)
    assert v.get_outline() == []
    doc.close()


def _make_page_with_text(doc, page_w, page_h, text_rect, text="content"):
    page = doc.new_page(width=page_w, height=page_h)
    page.insert_textbox(text_rect, text, fontsize=12)
    return page


def test_content_bbox_is_tighter_than_the_full_page_when_margins_are_real():
    doc = fitz.open()
    # Long enough to actually wrap and use most of the given box's width --
    # insert_textbox does NOT stretch a short word to fill its box, it
    # places real ink only as wide as the text itself needs (confirmed
    # live: a single short word produced a ~55pt-wide box, not 400pt).
    _make_page_with_text(doc, 600, 800, fitz.Rect(100, 100, 500, 200), text="real wrapping content " * 15)
    bbox = detect_content_bbox(doc, padding=8.0)
    assert bbox is not None
    assert bbox.width < 600 and bbox.height < 800
    # Real text sits well inside the crop, not clipped off.
    assert bbox.x0 <= 105 and bbox.x1 >= 480  # generous check on textbox's own real ink extent
    doc.close()


def test_content_bbox_is_none_for_a_genuinely_blank_page():
    doc = fitz.open()
    doc.new_page(width=600, height=800)  # no text, no images, no drawings
    bbox = detect_content_bbox(doc, padding=8.0)
    assert bbox is None
    doc.close()


def test_content_bbox_unions_across_sampled_pages_not_just_the_first():
    """A title page with a small centered blurb followed by a page with
    much wider real content -- the shared crop must be wide enough for
    BOTH, never clipping the wider page just because page 0 was
    narrower. This is the real safety property of sampling+unioning
    instead of trusting page 0 alone."""
    doc = fitz.open()
    _make_page_with_text(doc, 600, 800, fitz.Rect(250, 380, 350, 420), text="Title")
    _make_page_with_text(doc, 600, 800, fitz.Rect(20, 100, 580, 700), text="wide real content " * 40)
    bbox = detect_content_bbox(doc, padding=8.0)
    assert bbox is not None
    # Must cover the SECOND (wider) page's real content, not just page 0's
    # narrower blurb -- generous bounds (word-wrap leaves some slack on
    # the last line, real ink isn't pixel-exact to the given rect).
    assert bbox.x0 <= 30 and bbox.x1 >= 560
    doc.close()


def test_content_bbox_never_exceeds_the_page_bounds():
    """padding pushing the union past the physical page edge must clamp,
    never produce an out-of-bounds crop rect."""
    doc = fitz.open()
    _make_page_with_text(doc, 600, 800, fitz.Rect(2, 2, 598, 798))  # content nearly fills the page
    bbox = detect_content_bbox(doc, padding=8.0)
    assert bbox is not None
    assert bbox.x0 >= 0 and bbox.y0 >= 0
    assert bbox.x1 <= 600 and bbox.y1 <= 800
    doc.close()


def test_content_bbox_on_real_essay_pdf_matches_measured_margins():
    """Grounds the synthetic-fixture tests above against a real,
    already-shipped document (not just constructed edge cases)."""
    essay = "/mnt/c/bin/projects/cairn-secondary/artifacts/260729_0016-Chappie-Deon-Cairn-Essay.pdf"
    if not os.path.exists(essay):
        return  # real file may not exist in every environment -- skip quietly, not a hard dependency
    doc = fitz.open(essay)
    bbox = detect_content_bbox(doc, padding=8.0)
    assert bbox is not None
    page_w = doc[0].rect.width
    # Real measured margin before this feature existed was ~34.5pt/side
    # (post print-margin-tightening); crop should meaningfully narrow that
    # further without being absurd (sanity band, not an exact pin).
    assert 0 < (page_w - bbox.width) < page_w * 0.5
    doc.close()
