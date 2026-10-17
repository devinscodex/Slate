"""replace_file runs without a display, so these also run on the Windows
runner, where fsync and rename-over-open-file behave differently."""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io_pdf  # noqa: E402


def _make(path, text):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_replace_file_swaps_edits_in_over_the_open_file(tmp_path):
    path = str(tmp_path / "a.pdf")
    _make(path, "original")
    doc = fitz.open(path)
    doc[0].insert_text((72, 120), "EDITED", fontsize=12)
    new_doc = io_pdf.replace_file(doc, path)
    try:
        assert doc.is_closed
        assert "EDITED" in new_doc[0].get_text()
        with fitz.open(path) as reread:
            assert "EDITED" in reread[0].get_text()
        assert not os.path.exists(path + ".slate-tmp")
    finally:
        new_doc.close()


def test_replace_file_can_be_repeated(tmp_path):
    path = str(tmp_path / "a.pdf")
    _make(path, "original")
    doc = fitz.open(path)
    for n in range(3):
        doc[0].insert_text((72, 150 + n * 20), f"EDIT{n}", fontsize=12)
        doc = io_pdf.replace_file(doc, path)
    text = doc[0].get_text()
    doc.close()
    assert all(f"EDIT{n}" in text for n in range(3))


def test_replace_file_syncs_through_a_writable_handle(tmp_path, monkeypatch):
    fcntl = pytest.importorskip("fcntl")
    path = str(tmp_path / "a.pdf")
    _make(path, "original")
    real_fsync = os.fsync

    def strict_fsync(fd):
        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
            raise OSError(9, "Bad file descriptor")
        real_fsync(fd)

    monkeypatch.setattr(io_pdf.os, "fsync", strict_fsync)
    doc = fitz.open(path)
    io_pdf.replace_file(doc, path).close()


def test_failed_swap_hands_back_the_edited_document(tmp_path, monkeypatch):
    path = str(tmp_path / "a.pdf")
    _make(path, "original")
    before = open(path, "rb").read()
    doc = fitz.open(path)
    doc[0].insert_text((72, 120), "UNSAVED", fontsize=12)

    def refuse(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(io_pdf.os, "replace", refuse)
    with pytest.raises(PermissionError) as info:
        io_pdf.replace_file(doc, path)
    live = info.value.live_doc
    try:
        assert "UNSAVED" in live[0].get_text()
    finally:
        live.close()
    assert open(path, "rb").read() == before
    assert not os.path.exists(path + ".slate-tmp")
