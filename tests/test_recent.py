"""Slice 0 check: add/get, dedupe, cap-at-10, drop-missing-files. Tests
monkeypatch recent.CONFIG_DIR/RECENT_FILE to a tmp_path -- must never
touch the real ~/.slate/recent.json on the machine running the tests.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import recent  # noqa: E402


def _isolate(monkeypatch, tmp_path):
    cfg = tmp_path / ".slate"
    monkeypatch.setattr(recent, "CONFIG_DIR", cfg)
    monkeypatch.setattr(recent, "RECENT_FILE", cfg / "recent.json")


def test_add_and_get_round_trip(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    f = tmp_path / "a.pdf"
    f.write_text("x")
    recent.add_recent(str(f))
    entries = recent.get_recent()
    assert len(entries) == 1
    assert entries[0]["path"] == str(f.resolve()) or entries[0]["path"] == os.path.abspath(str(f))


def test_most_recent_first_and_dedupe(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_text("x")
    b.write_text("x")
    recent.add_recent(str(a))
    recent.add_recent(str(b))
    recent.add_recent(str(a))  # re-opening a should move it back to front
    entries = recent.get_recent()
    assert len(entries) == 2  # deduped, not 3
    assert entries[0]["path"] == os.path.abspath(str(a))
    assert entries[1]["path"] == os.path.abspath(str(b))


def test_caps_at_max_entries(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    paths = []
    for i in range(15):
        p = tmp_path / f"f{i}.pdf"
        p.write_text("x")
        paths.append(p)
        recent.add_recent(str(p))
    entries = recent.get_recent(limit=100)
    assert len(entries) == recent.MAX_ENTRIES
    # the most recently added ones should be the ones kept
    assert entries[0]["path"] == os.path.abspath(str(paths[-1]))


def test_missing_file_dropped_not_raised(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    f = tmp_path / "gone.pdf"
    f.write_text("x")
    recent.add_recent(str(f))
    assert len(recent.get_recent()) == 1
    f.unlink()
    entries = recent.get_recent()  # must not raise
    assert entries == []


def test_get_recent_with_no_file_yet(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    assert recent.get_recent() == []
