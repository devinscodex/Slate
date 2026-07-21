"""scan.py check: finds real SSN/routing/account/card-shaped content,
does not false-positive on plausible decoys, and flags image-only pages
as unscannable rather than silently reporting them clean. The label-on-
a-separate-line case is a real bug caught during development (a same-
line-only regex produced a false 'nothing found' against a real bank
letter) -- pinned here as its own named test, not just folded into the
general case.
"""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scan  # noqa: E402


def _page_with_lines(doc, lines):
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    return page


def test_ssn_found():
    doc = fitz.open()
    _page_with_lines(doc, ["Employee SSN: 123-45-6789", "unrelated line"])
    hits = scan.scan_document(doc)
    kinds = [h["kind"] for h in hits]
    assert "ssn" in kinds
    doc.close()


def test_luhn_valid_card_found_invalid_card_not_flagged():
    doc = fitz.open()
    # 4111111111111111 is the standard Luhn-valid Visa test number
    _page_with_lines(doc, ["Card on file: 4111 1111 1111 1111", "Reference: 1234 5678 9012 3456"])
    hits = scan.scan_document(doc)
    card_hits = [h for h in hits if h["kind"] == "card-number"]
    assert len(card_hits) == 1
    assert "4111" in card_hits[0]["value"]
    doc.close()


def test_label_and_value_on_separate_lines_regression(tmp_path):
    """Real bug, caught live auditing an actual bank letter: PyMuPDF's
    text extraction put 'Account Number:' and the digits on DIFFERENT
    lines with a blank line between them. The first version of this
    scanner used a same-line regex and silently reported the file
    clean. This test builds that exact layout (label / blank / value,
    each its own insert_text call -> its own line) and must still find
    it."""
    doc = fitz.open()
    _page_with_lines(
        doc,
        [
            "Account Number:",
            " ",
            "9825039777",
            "ABA (Routing) Number:",
            "101000695",
        ],
    )
    path = str(tmp_path / "labeled.pdf")
    doc.save(path)
    doc.close()

    reread = fitz.open(path)
    hits = scan.scan_document(reread)
    by_kind = {h["kind"]: h["value"] for h in hits}
    assert by_kind.get("account-number") == "9825039777"
    assert by_kind.get("routing-number") == "101000695"
    reread.close()


def test_bare_unlabeled_number_not_flagged():
    """A 9-digit or account-length number with NO label nearby should
    not be flagged -- otherwise this would fire on page numbers, dates,
    phone numbers, etc. constantly (too noisy to be useful)."""
    doc = fitz.open()
    _page_with_lines(doc, ["Invoice total due", "987654321", "Thank you for your business"])
    hits = scan.scan_document(doc)
    assert not any(h["kind"] in ("account-number", "routing-number") for h in hits)
    doc.close()


def test_image_only_page_flagged_unscannable_not_silently_clean():
    """The real gap found auditing Downloads: a page with zero
    extractable text (an image-only/scanned page) must be reported as
    UNSCANNABLE, not as 'scanned, nothing found' -- those are different
    claims and conflating them is exactly the failure mode this test
    guards against."""
    doc = fitz.open()
    page = doc.new_page()
    # a real image, no text layer at all
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8))
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(72, 72, 200, 200), pixmap=pix)
    hits = scan.scan_document(doc)
    assert any(h["kind"] == "unscannable" and h["page"] == 0 for h in hits)
    doc.close()


def test_hit_rect_resolves_back_to_the_page():
    """A found hit's rect should be usable directly as a redaction
    target (the real reason scan.py resolves rects at all -- so the UI
    can offer 'mark for redaction' straight from a scan result)."""
    doc = fitz.open()
    _page_with_lines(doc, ["SSN: 123-45-6789"])
    hits = scan.scan_document(doc)
    ssn_hits = [h for h in hits if h["kind"] == "ssn"]
    assert len(ssn_hits) == 1
    assert ssn_hits[0]["rect"] is not None
    assert not ssn_hits[0]["rect"].is_empty
    doc.close()


def test_scan_directory_batch_mode(tmp_path):
    clean_path = str(tmp_path / "clean.pdf")
    dirty_path = str(tmp_path / "dirty.pdf")

    doc1 = fitz.open()
    _page_with_lines(doc1, ["nothing sensitive here"])
    doc1.save(clean_path)
    doc1.close()

    doc2 = fitz.open()
    _page_with_lines(doc2, ["SSN: 123-45-6789"])
    doc2.save(dirty_path)
    doc2.close()

    results = scan.scan_directory(str(tmp_path))
    assert "dirty.pdf" in results
    assert "clean.pdf" not in results  # only files with hits are reported
