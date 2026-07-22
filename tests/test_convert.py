"""convert.py: PDF -> Markdown (hand-rolled, heading-by-relative-size),
PDF -> text, PDF <-> images. Real technique confirmed live before
writing this module (Document.convert_to_pdf() for image->PDF).
"""
import os

import fitz
from PIL import Image

import convert


def _make_doc_with_heading_body_and_bullets():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Big Title", fontsize=24, fontname="helv")
    page.insert_text((72, 100), "A normal paragraph sentence here.", fontsize=12, fontname="helv")
    page.insert_text((72, 130), "Subheading", fontsize=16, fontname="helv")
    page.insert_text((72, 160), "- bullet one", fontsize=12, fontname="helv")
    page.insert_text((72, 180), "- bullet two", fontsize=12, fontname="helv")
    return doc


def test_pdf_to_markdown_maps_larger_fonts_to_headings_by_rank():
    doc = _make_doc_with_heading_body_and_bullets()
    md = convert.pdf_to_markdown(doc)
    lines = md.splitlines()
    assert "# Big Title" in lines
    assert "## Subheading" in lines
    assert "A normal paragraph sentence here." in lines
    doc.close()


def test_pdf_to_markdown_normalizes_bullet_lines():
    doc = _make_doc_with_heading_body_and_bullets()
    md = convert.pdf_to_markdown(doc)
    assert "- bullet one" in md.splitlines()
    assert "- bullet two" in md.splitlines()
    doc.close()


def test_pdf_to_markdown_wraps_whole_line_bold_body_text():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    page.insert_text((72, 72), "Not bold body text.", fontsize=12, fontname="helv")
    page.insert_text((72, 100), "Bold body text.", fontsize=12, fontname="F1")
    d = page.get_text("dict")
    # sanity: confirm the bold span's flags really carry the bold bit
    # before trusting the wrap-in-** behavior below
    flags = [s["flags"] for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]
             if "Bold body" in s["text"]]
    assert flags and flags[0] & convert._FLAG_BOLD
    md = convert.pdf_to_markdown(doc)
    assert "**Bold body text.**" in md
    assert "Not bold body text." in md
    doc.close()


def test_pdf_to_markdown_empty_document_returns_empty_string():
    doc = fitz.open()
    doc.new_page()
    assert convert.pdf_to_markdown(doc) == ""
    doc.close()


def test_pdf_to_text_joins_pages_with_form_feed():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "page one text", fontsize=12)
    doc.new_page().insert_text((72, 72), "page two text", fontsize=12)
    text = convert.pdf_to_text(doc)
    assert "page one text" in text
    assert "page two text" in text
    assert "\f" in text
    assert text.index("page one text") < text.index("\f") < text.index("page two text")
    doc.close()


def test_pdf_to_images_writes_one_png_per_page(tmp_path):
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.new_page()
    out_dir = str(tmp_path / "out")
    written = convert.pdf_to_images(doc, out_dir, "report", dpi=100)
    assert len(written) == 3
    assert all(os.path.exists(p) for p in written)
    assert os.path.basename(written[0]) == "report_p1.png"
    assert os.path.basename(written[2]) == "report_p3.png"
    doc.close()


def test_pdf_to_images_respects_requested_dpi(tmp_path):
    doc = fitz.open()
    doc.new_page(width=72, height=72)  # exactly 1x1 inch
    out_dir = str(tmp_path / "out")
    written = convert.pdf_to_images(doc, out_dir, "sq", dpi=200)
    img = Image.open(written[0])
    assert img.size == (200, 200)  # 1 inch at 200 DPI
    doc.close()


def test_images_to_pdf_one_page_per_image(tmp_path):
    paths = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        p = str(tmp_path / f"img{i}.png")
        Image.new("RGB", (100, 150), color).save(p)
        paths.append(p)

    pdf = convert.images_to_pdf(paths)
    assert pdf.page_count == 3
    for page in pdf:
        assert page.rect.width > 0 and page.rect.height > 0
    pdf.close()


def test_images_to_pdf_preserves_input_order(tmp_path):
    paths = []
    sizes = [(50, 50), (200, 50), (50, 200)]
    for i, size in enumerate(sizes):
        p = str(tmp_path / f"img{i}.png")
        Image.new("RGB", size, (10, 10, 10)).save(p)
        paths.append(p)

    pdf = convert.images_to_pdf(paths)
    # each page's aspect ratio should track its source image's, in order
    ratios = [round(page.rect.width / page.rect.height, 1) for page in pdf]
    expected = [round(w / h, 1) for w, h in sizes]
    assert ratios == expected
    pdf.close()
