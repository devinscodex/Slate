"""In-place editing of existing body text (gated feature). Detect the
font a text span uses, pick the safest available way to reproduce it
for NEW text (reuse the exact embedded font > a real system font > a
Base-14 substitute, in that preference order), then redact-and-reinsert
at the same spot.

Uses a WHITE fill for its own redact-annot call, not redact.py's
mark_region() (black fill, correct for actual redaction) -- the two are
not interchangeable despite both being "add_redact_annot then apply".
"""
import fitz

import fontmatch

# PyMuPDF flag bits (confirmed via its own docs): bit0 superscript(1),
# bit1 italic(2), bit2 serifed(4), bit3 monospaced(8), bit4 bold(16).
FLAG_ITALIC = 2
FLAG_SERIF = 4
FLAG_MONOSPACE = 8
FLAG_BOLD = 16

_BASE14 = {
    ("serif", False, False): "tiro",
    ("serif", False, True): "tiit",
    ("serif", True, False): "tibo",
    ("serif", True, True): "tibi",
    ("mono", False, False): "cour",
    ("mono", False, True): "coit",
    ("mono", True, False): "cobo",
    ("mono", True, True): "cobi",
    ("sans", False, False): "helv",
    ("sans", False, True): "heit",
    ("sans", True, False): "hebo",
    ("sans", True, True): "hebi",
}

MIN_SHRINK_RATIO = 0.7  # don't shrink new text below 70% of the original size


class TextFitError(Exception):
    """Raised when new_text doesn't fit the original span's bbox even
    at the minimum shrink ratio -- callers must not silently overflow
    or truncate; the UI turns this into a real message to the user."""


def detect_span(page: fitz.Page, point: fitz.Point) -> dict:
    """The text span at a click point, or None. Real fields PyMuPDF
    actually exposes per span (verified via get_text('dict')): font
    name, size, flags bitfield, bbox, origin -- not assumed."""
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                bbox = fitz.Rect(span["bbox"])
                if bbox.contains(point):
                    return {
                        "text": span["text"],
                        "font": span["font"],
                        "size": span["size"],
                        "flags": span["flags"],
                        "bbox": bbox,
                        "origin": fitz.Point(span["origin"]),
                    }
    return None


def font_safety(doc: fitz.Document, page: fitz.Page, span: dict) -> str:
    """"reusable" | "system-font" | "substitute-needed". Checked in
    that preference order -- 1 and 2 both give real, non-approximated
    glyphs, only 3 needs a warning to the user.

    get_fonts()'s `name` field is the page's font-RESOURCE alias (e.g.
    "F1", whatever insert_font/the PDF producer chose as the dict key),
    NOT the same string as span["font"] (from get_text("dict"), the
    font's own internal name), even for a font this code just embedded.
    The correct comparison is span["font"] against `basefont` (the
    font's real reported name), normalized the same way fontmatch.py
    normalizes for registry/fontconfig comparisons, since the two
    naming schemes disagree on whitespace/style-suffix conventions too
    (e.g. "DejaVuSerif" vs "DejaVu Serif Book").
    """
    target = fontmatch._normalize_font_name(span["font"])
    for xref, ext, _type, basefont, name, _encoding in page.get_fonts():
        if ext == "n/a" or _is_subsetted(basefont):
            continue
        candidate = fontmatch._normalize_font_name(_strip_subset_prefix(basefont))
        if candidate == target or target in candidate or candidate in target:
            return "reusable"
    if fontmatch.find_system_font(span["font"]) is not None:
        return "system-font"
    return "substitute-needed"


def _strip_subset_prefix(basefont: str) -> str:
    return basefont[7:] if _is_subsetted(basefont) else basefont


def _is_subsetted(basefont: str) -> bool:
    """Subsetted fonts carry a 6-uppercase-letter+'+' prefix, e.g.
    'ABCDEF+Calibri' -- confirmed via PyMuPDF's own font-extraction
    docs/wiki, not assumed."""
    return len(basefont) > 7 and basefont[6] == "+" and basefont[:6].isupper() and basefont[:6].isalpha()


def substitute_font_for(flags: int) -> str:
    """Map the flags bitfield to the closest Base-14 alias. Never
    silently claims to be exact -- callers know this is tier 3."""
    family = "mono" if flags & FLAG_MONOSPACE else ("serif" if flags & FLAG_SERIF else "sans")
    bold = bool(flags & FLAG_BOLD)
    italic = bool(flags & FLAG_ITALIC)
    return _BASE14[(family, bold, italic)]


def edit_text(doc: fitz.Document, page: fitz.Page, span: dict, new_text: str, tier: str = None):
    """Redact the span's original text (white fill, not black -- see
    module docstring) and reinsert new_text at the same origin, using
    whichever font tier is safest. Shrinks fontsize toward
    MIN_SHRINK_RATIO if new_text is wider than the original bbox;
    raises TextFitError rather than silently overflow/truncate if it
    still doesn't fit at the floor."""
    tier = tier or font_safety(doc, page, span)
    fontname = "TE_font"
    fontfile = None
    fontbuffer = None

    if tier == "reusable":
        target = fontmatch._normalize_font_name(span["font"])
        for xref, ext, _type, basefont, name, _encoding in page.get_fonts():
            if ext == "n/a" or _is_subsetted(basefont):
                continue
            candidate = fontmatch._normalize_font_name(_strip_subset_prefix(basefont))
            if candidate == target or target in candidate or candidate in target:
                fontbuffer = doc.extract_font(xref)[-1]
                break
        else:
            raise ValueError("font_safety said 'reusable' but no matching embedded font found")
        font_obj = fitz.Font(fontbuffer=fontbuffer)
    elif tier == "system-font":
        fontfile = fontmatch.find_system_font(span["font"])
        if fontfile is None:
            raise ValueError("font_safety said 'system-font' but find_system_font returned None")
        font_obj = fitz.Font(fontfile=fontfile)
    else:
        fontname = substitute_font_for(span["flags"])
        font_obj = fitz.Font(fontname=fontname)

    size = span["size"]
    bbox_width = span["bbox"].width
    while font_obj.text_length(new_text, fontsize=size) > bbox_width and size > span["size"] * MIN_SHRINK_RATIO:
        size -= 0.5
    if font_obj.text_length(new_text, fontsize=size) > bbox_width:
        raise TextFitError(
            f"'{new_text}' does not fit the original text's space even at "
            f"{int(MIN_SHRINK_RATIO * 100)}% size -- refusing to overflow or truncate."
        )

    page.add_redact_annot(span["bbox"], fill=(1, 1, 1))
    page.apply_redactions(images=1, graphics=2, text=0)
    # Real bug caught here: registering the font via page.insert_font()
    # BEFORE apply_redactions() loses the registration -- apply_redactions
    # rebuilds page resources and drops any font not yet referenced by
    # the content stream. insert_text()'s own fontfile= param registers
    # a file-based font inline; a fontbuffer= (the reusable-tier case,
    # extracted bytes, no file path) still needs an explicit
    # insert_font() call, so that one is done last, right before use.
    if fontbuffer is not None:
        page.insert_font(fontname=fontname, fontbuffer=fontbuffer)
        page.insert_text(span["origin"], new_text, fontname=fontname, fontsize=size)
    elif fontfile is not None:
        page.insert_text(span["origin"], new_text, fontname=fontname, fontsize=size, fontfile=fontfile)
    else:
        page.insert_text(span["origin"], new_text, fontname=fontname, fontsize=size)
