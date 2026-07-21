"""Slice 1 check: every page of a fixture renders; dimensions/checksums are
deterministic and match expected."""
import hashlib
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from viewer import Viewer  # noqa: E402

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
