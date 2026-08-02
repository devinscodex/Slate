"""Slice 5 check: one of each widget type; set, reload, confirm
persisted; verify radio-sibling behavior specifically (DESIGN.md flags
this as the one real library gotcha -- verified here against the
actually-installed PyMuPDF version rather than assumed)."""
import os
import sys

import fitz
import pikepdf
from pikepdf import Array, Dictionary, Name, String

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forms  # noqa: E402


def _make_widget(rect, name, ftype, **extra):
    w = fitz.Widget()
    w.field_name = name
    w.field_type = ftype
    w.rect = rect
    for k, v in extra.items():
        setattr(w, k, v)
    return w


def _radio_kid(pdf, rect, on_name):
    ap_off = pdf.make_stream(b"q 1 1 1 RG 0.5 w 5 5 10 10 re S Q")
    ap_on = pdf.make_stream(b"q 0 0 0 RG 0.5 w 5 5 10 10 re S 8 8 4 4 re f Q")
    return pdf.make_indirect(
        Dictionary(
            Type=Name.Annot,
            Subtype=Name.Widget,
            Rect=Array(rect),
            F=4,
            AP=Dictionary(N=Dictionary({"/" + on_name: ap_on, "/Off": ap_off})),
            AS=Name.Off,
        )
    )


def _build_fixture(path):
    """text/checkbox/combo/listbox via PyMuPDF (all work fine standalone
    -- verified). Radio GROUP built via pikepdf directly: PyMuPDF cannot
    currently CREATE a new interlinked radio group (repeated add_widget()
    with a shared field_name raises "bad xref", confirmed via PyMuPDF
    GitHub discussion #2333 -- a real, sourced library limitation, not a
    Slate bug). Filling values on an existing group -- the actual v1
    feature -- works fine either way."""
    doc = fitz.open()
    page = doc.new_page()

    page.add_widget(_make_widget(fitz.Rect(72, 72, 300, 100), "name", fitz.PDF_WIDGET_TYPE_TEXT))
    page.add_widget(
        _make_widget(fitz.Rect(72, 110, 90, 128), "agree", fitz.PDF_WIDGET_TYPE_CHECKBOX)
    )
    page.add_widget(
        _make_widget(
            fitz.Rect(72, 170, 200, 195),
            "combo",
            fitz.PDF_WIDGET_TYPE_COMBOBOX,
            choice_values=["a", "b", "c"],
        )
    )
    page.add_widget(
        _make_widget(
            fitz.Rect(72, 200, 200, 240),
            "listbox",
            fitz.PDF_WIDGET_TYPE_LISTBOX,
            choice_values=["x", "y", "z"],
        )
    )
    doc.save(path)
    doc.close()

    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page0 = pdf.pages[0]
        kid_red = _radio_kid(pdf, [72, 140, 92, 160], "Red")
        kid_blue = _radio_kid(pdf, [100, 140, 120, 160], "Blue")
        parent = pdf.make_indirect(
            Dictionary(
                FT=Name.Btn,
                Ff=32768,
                T=String("color"),
                V=Name.Off,
                Kids=Array([kid_red, kid_blue]),
            )
        )
        kid_red.Parent = parent
        kid_blue.Parent = parent
        existing_annots = list(page0.Annots) if "/Annots" in page0 else []
        page0.Annots = Array(existing_annots + [kid_red, kid_blue])
        existing_fields = (
            list(pdf.Root.AcroForm.Fields) if "/AcroForm" in pdf.Root else []
        )
        pdf.Root.AcroForm = Dictionary(
            Fields=Array(existing_fields + [parent]), NeedAppearances=True
        )
        pdf.save(path)


def test_one_of_each_widget_type_persists(tmp_path):
    path = str(tmp_path / "form.pdf")
    _build_fixture(path)

    doc = fitz.open(path)
    page = doc[0]
    by_name = forms.widgets_by_name(page)
    assert set(by_name) == {"name", "agree", "combo", "listbox", "color"}
    assert len(by_name["color"]) == 2  # the radio group's two kids

    forms.set_text(by_name["name"][0], "Devin")
    forms.set_checkbox(by_name["agree"][0], True)
    forms.set_combo(by_name["combo"][0], "b")
    forms.set_listbox(by_name["listbox"][0], "y")
    doc.save(path.replace(".pdf", "_filled.pdf"))
    doc.close()

    reread = fitz.open(path.replace(".pdf", "_filled.pdf"))
    page2 = reread[0]  # keep a live reference -- widgets hold a weak ref
    # to their parent page/doc; letting that go out of scope breaks
    # radio-group updates later (see test_radio_sibling_auto_unset).
    by_name2 = forms.widgets_by_name(page2)
    assert by_name2["name"][0].field_value == "Devin"
    # a checkbox's ON value is its own on_state() name (commonly "Yes",
    # not the Python bool True) -- confirmed directly rather than assumed.
    checkbox = by_name2["agree"][0]
    assert checkbox.field_value == checkbox.on_state()
    assert by_name2["combo"][0].field_value == "b"
    assert by_name2["listbox"][0].field_value == "y"
    reread.close()


def test_radio_sibling_auto_unset(tmp_path):
    """The one real gotcha DESIGN.md names -- verify it directly against
    the installed PyMuPDF version rather than trust the earlier research.
    Result (see commit message): this version DOES auto-unset siblings
    via Widget._checker(), contradicting the originally-cited limitation.
    This test pins that behavior so a future PyMuPDF upgrade that
    regresses it gets caught immediately."""
    path = str(tmp_path / "radio.pdf")
    _build_fixture(path)

    doc = fitz.open(path)
    page = doc[0]  # keep a live reference -- see note in the other test:
    # widgets hold a weak ref to their parent page, and letting it be
    # collected mid-scope turns radio sibling-unset into a ReferenceError
    # ("weakly-referenced object no longer exists") rather than a clean
    # set. Real bug hit while writing this test, fixed by keeping `page`
    # bound for as long as any of its widgets are still being updated.
    by_name = forms.widgets_by_name(page)
    red, blue = by_name["color"]

    forms.set_radio(red, "Red")
    forms.set_radio(blue, "Blue")
    out = str(tmp_path / "radio_out.pdf")
    doc.save(out)
    doc.close()

    reread = fitz.open(out)
    page2 = reread[0]
    by_name2 = forms.widgets_by_name(page2)
    red2, blue2 = by_name2["color"]
    # Only the LAST one set should be ON; the other must have been
    # auto-forced back to Off -- this is the actual bug class DESIGN.md
    # was written to guard against (two "mutually exclusive" options
    # both appearing checked).
    values = {red2.field_value, blue2.field_value}
    assert values == {"Blue", "Off"}, (
        f"expected exactly one radio ON and the other forced Off, got {values} "
        "-- if this fails, PyMuPDF's auto-unset regressed and forms.py needs "
        "the manual sibling-unset logic DESIGN.md originally called for"
    )
    reread.close()
