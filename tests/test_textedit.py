"""Slice 2 check: detect_span, font_safety (all 3 tiers), edit_text
(reuse/substitute paths, fit-shrink, and the too-long-even-at-floor
raise). Reuses the exact fixture-building pattern from slice 0's real
font-fidelity experiment (DESIGN.md) -- a genuinely embedded,
non-subsetted font, confirmed via get_fonts(), not assumed.
"""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fontmatch  # noqa: E402
import textedit  # noqa: E402

# Real bug caught on an actual Windows smoke test: this used to
# hardcode a Linux-only path, which fitz.Page.insert_font() then
# failed to open there. A small existence-checked candidate list
# instead of one hardcoded assumption -- same fix as test_convert.py/
# test_integration.py.
_EMBEDDABLE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",  # Linux (Debian/Ubuntu)
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",  # Linux (Fedora)
    r"C:\Windows\Fonts\times.ttf",  # Windows
]
REAL_EMBEDDABLE_FONT = next((p for p in _EMBEDDABLE_FONT_CANDIDATES if os.path.exists(p)), None)
# The font's own internal name (what PyMuPDF reports as span["font"]),
# derived from whichever real font was actually resolved above rather
# than hardcoded -- "DejaVuSerif" on Linux, "Times New Roman" on
# Windows, etc.
REAL_EMBEDDABLE_FONT_NAME = (
    fitz.Font(fontfile=REAL_EMBEDDABLE_FONT).name if REAL_EMBEDDABLE_FONT else None
)


def _normalize_spaces(text: str) -> str:
    """Real font-file-specific quirk caught on an actual Windows smoke
    test: PyMuPDF/MuPDF renders inserted spaces as regular ASCII spaces
    for some embedded fonts (DejaVuSerif on Linux) but as non-breaking
    spaces (U+00A0) for others (Times New Roman on Windows) -- neither
    is wrong, just a real difference in how each font's own glyph table
    is interpreted. Assertions here care about the WORDS, not the exact
    whitespace byte, so this normalizes before comparing."""
    return text.replace("\xa0", " ")


def _make_reusable_fixture(path, text="The quick brown fox jumps over the lazy dog."):
    if REAL_EMBEDDABLE_FONT is None:
        pytest.skip("no known real embeddable font found on this machine")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile=REAL_EMBEDDABLE_FONT)
    page.insert_text(fitz.Point(72, 100), text, fontname="F1", fontsize=14)
    doc.save(path)
    doc.close()


def _make_base14_fixture(path, text="The quick brown fox jumps over the lazy dog."):
    """Base-14 fonts inserted without insert_font are never embedded
    (confirmed: get_fonts() reports ext=='n/a' for these) -- the real
    starting point for both the system-font and substitute-needed
    tiers, which both apply when nothing is safely reusable."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 100), text, fontname="helv", fontsize=14)
    doc.save(path)
    doc.close()


def test_detect_span_finds_text_at_a_point_and_misses_elsewhere(tmp_path):
    path = str(tmp_path / "f.pdf")
    _make_reusable_fixture(path)
    doc = fitz.open(path)
    page = doc[0]

    span = textedit.detect_span(page, fitz.Point(80, 95))
    assert span is not None
    assert "quick brown fox" in _normalize_spaces(span["text"])
    assert span["font"] == REAL_EMBEDDABLE_FONT_NAME  # PyMuPDF's internal font name, not the resource alias "F1"

    nothing = textedit.detect_span(page, fitz.Point(80, 500))
    assert nothing is None
    doc.close()


def test_font_safety_reusable_for_embedded_nonsubsetted_font(tmp_path):
    path = str(tmp_path / "f.pdf")
    _make_reusable_fixture(path)
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(80, 95))
    assert textedit.font_safety(doc, page, span) == "reusable"
    doc.close()


def test_font_safety_system_font_when_not_embedded_but_installed(tmp_path, monkeypatch):
    path = str(tmp_path / "f.pdf")
    _make_base14_fixture(path)  # "helv" -> not embedded (ext == 'n/a')
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(80, 95))

    monkeypatch.setattr(fontmatch, "find_system_font", lambda name: "/fake/path/font.ttf")
    assert textedit.font_safety(doc, page, span) == "system-font"
    doc.close()


def test_font_safety_substitute_needed_when_nothing_else_works(tmp_path, monkeypatch):
    path = str(tmp_path / "f.pdf")
    _make_base14_fixture(path)
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(80, 95))

    monkeypatch.setattr(fontmatch, "find_system_font", lambda name: None)
    assert textedit.font_safety(doc, page, span) == "substitute-needed"
    doc.close()


def test_substitute_font_for_maps_flags_correctly():
    assert textedit.substitute_font_for(0) == "helv"  # sans, regular
    assert textedit.substitute_font_for(textedit.FLAG_BOLD) == "hebo"
    assert textedit.substitute_font_for(textedit.FLAG_ITALIC) == "heit"
    assert textedit.substitute_font_for(textedit.FLAG_BOLD | textedit.FLAG_ITALIC) == "hebi"
    assert textedit.substitute_font_for(textedit.FLAG_SERIF) == "tiro"
    assert textedit.substitute_font_for(textedit.FLAG_SERIF | textedit.FLAG_BOLD) == "tibo"
    assert textedit.substitute_font_for(textedit.FLAG_MONOSPACE) == "cour"


def test_edit_text_reusable_tier_end_to_end(tmp_path):
    path = str(tmp_path / "f.pdf")
    out = str(tmp_path / "edited.pdf")
    _make_reusable_fixture(path)
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(80, 95))

    assert textedit.font_safety(doc, page, span) == "reusable"
    textedit.edit_text(doc, page, span, "A slow purple wolf sleeps under the bright sun.")
    doc.save(out)
    doc.close()

    reread = fitz.open(out)
    text = _normalize_spaces(reread[0].get_text())
    assert "slow purple wolf" in text
    assert "quick brown fox" not in text
    # confirm it's still using a real embedded (non-substitute) font
    fonts = reread[0].get_fonts()
    assert any(f[1] != "n/a" for f in fonts)
    reread.close()


def test_edit_text_substitute_tier_end_to_end(tmp_path):
    path = str(tmp_path / "f.pdf")
    out = str(tmp_path / "edited.pdf")
    _make_base14_fixture(path)
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(80, 95))

    textedit.edit_text(doc, page, span, "Different words entirely here now.", tier="substitute-needed")
    doc.save(out)
    doc.close()

    reread = fitz.open(out)
    text = _normalize_spaces(reread[0].get_text())
    assert "Different words entirely" in text
    assert "quick brown fox" not in text
    reread.close()


def test_edit_text_shrinks_to_fit_longer_replacement(tmp_path):
    path = str(tmp_path / "f.pdf")
    out = str(tmp_path / "edited.pdf")
    # a short original so a longer replacement forces the shrink path
    _make_base14_fixture(path, text="Hi.")
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(75, 95))
    # widen the detected bbox a little to something realistic but still
    # tight, so a longer sentence needs shrinking, not just fitting free
    span["bbox"] = fitz.Rect(span["bbox"].x0, span["bbox"].y0, span["bbox"].x0 + 90, span["bbox"].y1)

    textedit.edit_text(doc, page, span, "Longer text here.", tier="substitute-needed")
    doc.save(out)
    doc.close()

    reread = fitz.open(out)
    assert "Longer text here." in _normalize_spaces(reread[0].get_text())
    reread.close()


def test_edit_text_raises_when_it_cannot_fit_even_at_floor(tmp_path):
    path = str(tmp_path / "f.pdf")
    _make_base14_fixture(path, text="Hi.")
    doc = fitz.open(path)
    page = doc[0]
    span = textedit.detect_span(page, fitz.Point(75, 95))
    span["bbox"] = fitz.Rect(span["bbox"].x0, span["bbox"].y0, span["bbox"].x0 + 20, span["bbox"].y1)

    with pytest.raises(textedit.TextFitError):
        textedit.edit_text(
            doc,
            page,
            span,
            "This entire sentence is far too long to ever fit in twenty points of width.",
            tier="substitute-needed",
        )
    doc.close()
