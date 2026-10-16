"""Structural check of produced PDFs with qpdf, independent of the
libraries that wrote them. Skipped when qpdf is not installed."""
import os
import shutil
import subprocess
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io_pdf  # noqa: E402
import merge_split  # noqa: E402
import redact  # noqa: E402

QPDF = shutil.which("qpdf")
pytestmark = pytest.mark.skipif(QPDF is None, reason="qpdf not installed")


def _doc(labels):
    doc = fitz.open()
    for label in labels:
        doc.new_page().insert_text((72, 72), label, fontsize=14)
    return doc


def _check(path):
    r = subprocess.run([QPDF, "--check", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_safe_save_output_is_valid(tmp_path):
    p = tmp_path / "saved.pdf"
    io_pdf.safe_save(_doc(["a", "b"]), str(p))
    _check(p)


def test_merge_output_is_valid(tmp_path):
    paths = []
    for i, labels in enumerate((["a1", "a2"], ["b1"])):
        p = tmp_path / f"in{i}.pdf"
        _doc(labels).save(str(p))
        paths.append(str(p))
    out = tmp_path / "merged.pdf"
    io_pdf.safe_save(merge_split.merge_pdfs(paths), str(out))
    _check(out)


def test_split_outputs_are_valid(tmp_path):
    for i, part in enumerate(merge_split.split_pdf(_doc(["a", "b", "c"]))):
        p = tmp_path / f"part{i}.pdf"
        io_pdf.safe_save(part, str(p))
        _check(p)


def test_redacted_output_is_valid(tmp_path):
    doc = _doc(["secret text"])
    redact.mark_region(doc[0], fitz.Rect(60, 55, 200, 85))
    redact.apply_all(doc)
    redact.strip_metadata(doc)
    p = tmp_path / "redacted.pdf"
    io_pdf.safe_save(doc, str(p))
    _check(p)
