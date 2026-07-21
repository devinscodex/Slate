"""Slice check: search.py's find_all_matches (real PyMuPDF search_for,
case-insensitivity confirmed live) and SearchState's next/prev
wraparound navigation.
"""
import fitz

import search


def _doc_with_pages(texts):
    doc = fitz.open()
    for t in texts:
        doc.new_page().insert_text((72, 72), t, fontsize=14)
    return doc


def test_find_all_matches_across_multiple_pages_in_page_order():
    doc = _doc_with_pages(["needle here", "nothing", "another needle"])
    matches = search.find_all_matches(doc, "needle")
    assert [p for p, _ in matches] == [0, 2]
    doc.close()


def test_find_all_matches_is_case_insensitive():
    doc = _doc_with_pages(["Hello World"])
    assert len(search.find_all_matches(doc, "hello")) == 1
    assert len(search.find_all_matches(doc, "HELLO")) == 1
    doc.close()


def test_find_all_matches_empty_query_returns_empty_not_none():
    """Real gotcha: page.search_for("") itself returns None, not [] --
    confirmed live before writing this test. find_all_matches must not
    leak that None through."""
    doc = _doc_with_pages(["some text"])
    assert search.find_all_matches(doc, "") == []
    assert search.find_all_matches(doc, "   ") == []
    doc.close()


def test_find_all_matches_no_hits_returns_empty_list():
    doc = _doc_with_pages(["some text"])
    assert search.find_all_matches(doc, "nonexistent") == []
    doc.close()


def test_search_state_run_sets_first_match_current():
    doc = _doc_with_pages(["alpha", "beta alpha"])
    state = search.SearchState()
    state.run(doc, "alpha")
    assert len(state.matches) == 2
    assert state.current()[0] == 0
    doc.close()


def test_search_state_run_with_no_hits_has_no_current():
    doc = _doc_with_pages(["alpha"])
    state = search.SearchState()
    state.run(doc, "zzz")
    assert state.matches == []
    assert state.current() is None
    doc.close()


def test_search_state_advance_and_retreat_wrap_around():
    doc = _doc_with_pages(["x", "x", "x"])
    state = search.SearchState()
    state.run(doc, "x")
    assert len(state.matches) == 3
    assert state.index == 0

    state.advance()
    assert state.index == 1
    state.advance()
    assert state.index == 2
    state.advance()  # wraps
    assert state.index == 0

    state.retreat()  # wraps the other way
    assert state.index == 2
    doc.close()


def test_matches_on_page_filters_correctly():
    doc = _doc_with_pages(["needle", "nothing", "needle"])
    state = search.SearchState()
    state.run(doc, "needle")
    assert len(state.matches_on_page(0)) == 1
    assert len(state.matches_on_page(1)) == 0
    assert len(state.matches_on_page(2)) == 1
    doc.close()
