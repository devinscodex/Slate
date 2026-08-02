"""Slice 3 check: merge/split/extract/reorder round-trip page count and
per-page text exactly."""
import hashlib
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_split  # noqa: E402


def _make_doc(labels: list) -> fitz.Document:
    """A doc with one page per label, each page's text uniquely
    identifying it (so we can tell pages apart after reordering)."""
    doc = fitz.open()
    for label in labels:
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=14)
    return doc


def _text_hashes(doc: fitz.Document) -> list:
    return [hashlib.sha256(doc[i].get_text().encode()).hexdigest() for i in range(doc.page_count)]


def test_merge_preserves_page_count_and_order(tmp_path):
    doc_a = _make_doc(["A1", "A2"])
    doc_b = _make_doc(["B1", "B2", "B3"])
    path_a, path_b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    doc_a.save(path_a)
    doc_b.save(path_b)
    doc_a.close()
    doc_b.close()

    merged = merge_split.merge_pdfs([path_a, path_b])
    assert merged.page_count == 5
    texts = [merged[i].get_text().strip() for i in range(merged.page_count)]
    assert texts == ["A1", "A2", "B1", "B2", "B3"]
    merged.close()


def test_split_then_remerge_round_trips_exactly(tmp_path):
    original = _make_doc(["one", "two", "three"])
    orig_hashes = _text_hashes(original)
    path = str(tmp_path / "orig.pdf")
    original.save(path)
    original.close()

    doc = fitz.open(path)
    parts = merge_split.split_pdf(doc)
    assert len(parts) == 3
    assert all(p.page_count == 1 for p in parts)

    part_paths = []
    for i, part in enumerate(parts):
        p = str(tmp_path / f"part{i}.pdf")
        part.save(p)
        part.close()
        part_paths.append(p)
    doc.close()

    remerged = merge_split.merge_pdfs(part_paths)
    assert remerged.page_count == 3
    assert _text_hashes(remerged) == orig_hashes
    remerged.close()


def test_extract_pages_selects_and_reorders(tmp_path):
    doc = _make_doc(["p0", "p1", "p2", "p3"])
    extracted = merge_split.extract_pages(doc, [3, 0, 0])
    assert extracted.page_count == 3
    texts = [extracted[i].get_text().strip() for i in range(3)]
    assert texts == ["p3", "p0", "p0"]  # order + repeats both honored
    doc.close()
    extracted.close()


def test_reorder_pages_in_place():
    doc = _make_doc(["p0", "p1", "p2"])
    merge_split.reorder_pages(doc, [2, 0, 1])
    texts = [doc[i].get_text().strip() for i in range(doc.page_count)]
    assert texts == ["p2", "p0", "p1"]
    doc.close()


def test_reorder_rejects_non_permutation():
    doc = _make_doc(["p0", "p1", "p2"])
    try:
        merge_split.reorder_pages(doc, [0, 1])  # missing page 2
        assert False, "expected ValueError for a non-permutation"
    except ValueError:
        pass
    doc.close()
