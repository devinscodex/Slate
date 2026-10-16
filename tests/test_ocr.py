"""OCR check: an image-only page gains searchable text, native-text pages
are left alone, redaction removes OCR text, and rotated pages still search."""
import os
import sys

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io_pdf  # noqa: E402
import ocr  # noqa: E402
import redact  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
pytestmark = pytest.mark.skipif(
    not ocr.available() or not os.path.exists(FONT), reason="OCR data or test font missing"
)


def _scan_page(doc, lines, path, rotation=0):
    """An image-only page. With rotation, the stored image is turned so the
    page displays upright once /Rotate is applied."""
    img = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 40)
    for n, line in enumerate(lines):
        draw.text((40, 50 + n * 100), line, font=font, fill="black")
    w, h = 450, 150
    if rotation:
        img = img.rotate(rotation, expand=True)
        w, h = h, w
    img.save(path)
    page = doc.new_page(width=w, height=h)
    page.insert_image(page.rect, filename=path)
    if rotation:
        page.set_rotation(rotation)
    return page


def test_scanned_page_gains_searchable_text(tmp_path):
    doc = fitz.open()
    page = _scan_page(doc, ["Invoice 4821 total", "Confidential ledger"], str(tmp_path / "s.png"))
    assert ocr.page_needs_ocr(page)
    assert page.search_for("Confidential") == []
    result = ocr.ocr_document(doc)
    assert result[0] >= 4
    assert page.search_for("Confidential")
    assert "4821" in page.get_text()
    assert not ocr.page_needs_ocr(page)


def test_text_pages_are_skipped():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "already has plenty of real text", fontsize=12)
    assert not ocr.page_needs_ocr(doc[0])
    assert ocr.ocr_document(doc) == {}


def test_ocr_text_is_invisible_and_image_is_kept(tmp_path):
    doc = fitz.open()
    page = _scan_page(doc, ["Hidden words here"], str(tmp_path / "s.png"))
    before = page.get_pixmap(dpi=72).samples
    ocr.ocr_page(page)
    assert page.get_pixmap(dpi=72).samples == before
    assert page.get_image_info()


def test_redaction_removes_ocr_text(tmp_path):
    doc = fitz.open()
    page = _scan_page(doc, ["Secret number 9917"], str(tmp_path / "s.png"))
    ocr.ocr_page(page)
    hits = page.search_for("9917")
    assert hits
    redact.mark_region(page, hits[0])
    redact.apply_all(doc)
    out = str(tmp_path / "out.pdf")
    io_pdf.safe_save(doc, out)
    assert "9917" not in fitz.open(out)[0].get_text()


def test_rotated_page_text_still_searches(tmp_path):
    doc = fitz.open()
    page = _scan_page(doc, ["Rotated page words"], str(tmp_path / "s.png"), rotation=90)
    ocr.ocr_page(page)
    assert page.rotation == 90
    hits = page.search_for("Rotated")
    assert hits
    shown = hits[0] * page.rotation_matrix
    assert page.rect.contains(shown)
    assert shown.y0 < page.rect.height / 2  # first line sits in the top half
