"""Slice 2 -- the trust gate. Redaction must genuinely remove content,
not just visually cover it (DESIGN.md). Every assertion here is checked
two independent ways where possible: PyMuPDF's own reader AND pikepdf
(QPDF-backed, a different codebase) -- never let the engine that wrote
the file grade its own redaction. The "unsafe path" tests exist to prove
the hardening in io_pdf.safe_save is load-bearing, not decorative.
"""
import hashlib
import io
import os
import sys

import fitz
import pikepdf
from PIL import Image
from pdfminer.high_level import extract_text as pdfminer_extract_text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io_pdf  # noqa: E402
import redact  # noqa: E402

CANARY_TEXT = "SLATE-CANARY-4f8b2c-DO-NOT-SURVIVE-REDACTION"
CANARY_RECT = fitz.Rect(72, 72, 400, 100)
CANARY_IMG_RECT = fitz.Rect(72, 150, 172, 250)


def _canary_image_bytes():
    """An 8x8 solid, distinctive-color PNG -- small, deterministic pixel
    content we can hash and hunt for after redaction."""
    img = Image.new("RGB", (8, 8), (37, 211, 199))  # an arbitrary, unlikely-
    # to-occur-by-chance color
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _canary_pixel_hash():
    img = Image.new("RGB", (8, 8), (37, 211, 199))
    return hashlib.sha256(img.tobytes()).hexdigest()


def _build_fixture(path, with_incremental_history=False):
    """Build a fixture with a canary text string and a canary image at
    known locations. If with_incremental_history, save once, then make
    a trivial unrelated incremental edit and save again -- so by the
    time redaction runs, the file already carries real prior-revision
    bytes, exactly the scenario DESIGN.md flags as risky."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((CANARY_RECT.x0, CANARY_RECT.y0 + 15), CANARY_TEXT, fontsize=12)
    page.insert_image(CANARY_IMG_RECT, stream=_canary_image_bytes())
    doc.save(path)
    doc.close()

    if with_incremental_history:
        doc = fitz.open(path)
        # trivial, unrelated edit -- do NOT touch the canary region
        doc[0].insert_text((72, 700), "unrelated later annotation")
        doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        doc.close()


def _raw_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _canary_in_raw_bytes(path):
    """PyMuPDF's insert_text stores text as hex-encoded glyph codes
    (`<534c4154...>` in the content stream), not literal ASCII bytes --
    confirmed by inspecting page.read_contents() directly. On top of
    that, PyMuPDF FlateDecode-compresses that content stream on disk
    even with save()'s deflate default -- confirmed via pikepdf
    (Contents[0]'s /Filter is /FlateDecode regardless). A plain
    substring search over the raw file therefore proves nothing either
    way; this brute-forces every zlib-looking offset in the file,
    decompresses it, and searches the decompressed bytes instead --
    the same thing a forensic recovery attempt would do, and it works
    regardless of which xref generation a chunk belongs to (unlike
    pikepdf's/PyMuPDF's own object walk, which only sees the CURRENT
    generation -- the reason this exists at all is to independently
    check prior, superseded revisions too)."""
    import zlib

    raw = _raw_bytes(path)
    literal = CANARY_TEXT.encode()
    hexed = CANARY_TEXT.encode().hex().encode()
    needles = (literal, hexed, hexed.upper())
    if any(n in raw for n in needles):
        return True
    for i in range(len(raw) - 1):
        if raw[i] != 0x78:  # common zlib header first byte
            continue
        try:
            chunk = zlib.decompress(raw[i:])
        except zlib.error:
            continue
        if any(n in chunk for n in needles):
            return True
    return False


def _canary_image_survives(path):
    """Decode every image left in the document and compare pixel hash
    to the canary's -- catches the image surviving under any encoding,
    not just a raw-byte match (PyMuPDF re-encodes on insert, so a raw
    PNG byte search would miss a re-encoded but still-recoverable copy)."""
    target = _canary_pixel_hash()
    doc = fitz.open(path)
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                extracted = doc.extract_image(xref)
            except Exception:
                continue
            try:
                pixels = Image.open(io.BytesIO(extracted["image"])).convert("RGB")
                if pixels.size != (8, 8):
                    continue
                if hashlib.sha256(pixels.tobytes()).hexdigest() == target:
                    doc.close()
                    return True
            except Exception:
                continue
    doc.close()
    return False


def _pikepdf_scan_for_canary(path):
    """Independent second reader: walk every object pikepdf can reach
    (including decompressing streams) and search for the canary text --
    in both its literal and hex-glyph-encoded forms (see
    _canary_in_raw_bytes for why both matter)."""
    literal = CANARY_TEXT.encode()
    hexed = CANARY_TEXT.encode().hex().encode()
    needles = (literal, hexed, hexed.upper())
    with pikepdf.open(path) as pdf:
        for obj in pdf.objects:
            try:
                if obj.is_stream:
                    data = obj.read_bytes()
                else:
                    data = repr(obj).encode(errors="ignore")
                if any(n in data for n in needles):
                    return True
            except Exception:
                continue
    return False


def _pdfminer_scan_for_canary(path):
    """Third independent reader, and a genuinely different codebase from
    both PyMuPDF and pikepdf -- already the established text-extraction
    tool in this project (the markitdown skill). Decodes glyph encodings
    the way a real extraction tool would, unlike a raw byte/hex search."""
    return CANARY_TEXT in pdfminer_extract_text(path)


def _redact_canary(doc):
    redact.mark_region(doc[0], CANARY_RECT)
    redact.mark_region(doc[0], CANARY_IMG_RECT)
    redact.apply_all(doc)
    redact.strip_metadata(doc)


# ---------------------------------------------------------------------
# Sanity: prove the fixture itself actually contains the canary before
# we ever redact anything -- a test that "passes" against an empty
# fixture would be worthless.
# ---------------------------------------------------------------------

def test_fixture_actually_contains_canary(tmp_path):
    path = str(tmp_path / "plain.pdf")
    _build_fixture(path)
    assert _canary_in_raw_bytes(path)
    doc = fitz.open(path)
    assert CANARY_TEXT in doc[0].get_text()
    doc.close()
    assert _canary_image_survives(path)


def test_incremental_fixture_has_real_revision_history(tmp_path):
    path = str(tmp_path / "incr.pdf")
    _build_fixture(path, with_incremental_history=True)
    raw = _raw_bytes(path)
    # A real incremental save appends a second "%%EOF" trailer; a single-
    # revision file has exactly one. This is the fixture-validity check --
    # if this fails, the fixture doesn't actually exercise the risky path.
    assert raw.count(b"%%EOF") >= 2


# ---------------------------------------------------------------------
# THE TRUST GATE: safe_save must leave the canary unrecoverable, by
# every check, on both fixtures.
# ---------------------------------------------------------------------

def test_redaction_removes_canary_plain_fixture(tmp_path):
    src = str(tmp_path / "plain.pdf")
    out = str(tmp_path / "plain_redacted.pdf")
    _build_fixture(src)

    doc = fitz.open(src)
    _redact_canary(doc)
    io_pdf.safe_save(doc, out)
    doc.close()

    reread = fitz.open(out)
    assert CANARY_TEXT not in reread[0].get_text()
    reread.close()
    assert not _canary_in_raw_bytes(out)
    assert not _canary_image_survives(out)
    assert not _pikepdf_scan_for_canary(out)
    assert not _pdfminer_scan_for_canary(out)


def test_redaction_removes_canary_with_prior_incremental_history(tmp_path):
    """The scenario DESIGN.md flags explicitly: the source file already
    has a prior revision's bytes physically in it before we ever touch
    it. A full-rewrite safe_save must still leave nothing recoverable."""
    src = str(tmp_path / "incr.pdf")
    out = str(tmp_path / "incr_redacted.pdf")
    _build_fixture(src, with_incremental_history=True)

    doc = fitz.open(src)
    _redact_canary(doc)
    io_pdf.safe_save(doc, out)
    doc.close()

    reread = fitz.open(out)
    assert CANARY_TEXT not in reread[0].get_text()
    reread.close()
    assert not _canary_in_raw_bytes(out)
    assert not _canary_image_survives(out)
    assert not _pikepdf_scan_for_canary(out)
    assert not _pdfminer_scan_for_canary(out)


# ---------------------------------------------------------------------
# Prove the hardening is load-bearing: the SAME redaction, saved through
# an unsafe path, must still leak the canary. If these tests fail (i.e.
# the canary is ALSO gone via the unsafe path), the "safe" path isn't
# proven to matter -- these are the negative controls.
# ---------------------------------------------------------------------

def test_unsafe_no_garbage_collection_leaks_canary(tmp_path):
    src = str(tmp_path / "plain.pdf")
    out = str(tmp_path / "plain_unsafe.pdf")
    _build_fixture(src)

    doc = fitz.open(src)
    _redact_canary(doc)
    io_pdf.unsafe_save_for_testing(doc, out)
    doc.close()

    # The current-revision text/image are gone (redaction itself worked),
    # but skipping garbage collection can leave the ORIGINAL, pre-redaction
    # object bytes as orphaned-but-present data in the output file.
    assert _canary_in_raw_bytes(out), (
        "expected the unsafe (garbage=0) path to leak the canary -- if it "
        "didn't, this negative control no longer proves garbage=4 matters"
    )


def test_unsafe_incremental_save_leaks_prior_revision(tmp_path):
    """Redact, then save INCREMENTALLY back to the same path the prior-
    revision fixture came from. Incremental save appends new xref/objects
    without touching existing bytes -- the pre-redaction revision's bytes
    (including the canary) must still be sitting in the file."""
    path = str(tmp_path / "incr.pdf")
    _build_fixture(path, with_incremental_history=True)

    doc = fitz.open(path)
    _redact_canary(doc)
    doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()

    assert _canary_in_raw_bytes(path), (
        "expected an incremental save to leave the canary recoverable in "
        "the file's own revision history -- if it didn't, this negative "
        "control no longer proves incremental=False matters"
    )
