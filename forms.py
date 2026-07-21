"""AcroForm fill: text/checkbox/radio/combo/listbox. Slate fills EXISTING
form fields (received PDFs) -- authoring brand-new radio groups is out of
v1 scope, and separately has a real PyMuPDF limitation (see DESIGN.md):
creating a new interlinked radio group via repeated add_widget() calls
raises "bad xref". Filling values on an existing group works fine and is
what this module does.
"""
import fitz


def set_value(widget: fitz.Widget, value):
    """Set any widget's value and persist it. For radio buttons, the
    installed PyMuPDF version (1.28.0, verified directly -- see
    DESIGN.md) auto-unsets sibling buttons in the same group via its own
    Widget._checker(), so no manual sibling-unset is needed here."""
    widget.field_value = value
    widget.update()


def set_text(widget: fitz.Widget, text: str):
    set_value(widget, text)


def set_checkbox(widget: fitz.Widget, checked: bool):
    set_value(widget, checked)


def set_radio(widget: fitz.Widget, value):
    """value must be one of widget.button_states()['normal'] (the ON
    name, e.g. 'Red') or 'Off'."""
    set_value(widget, value)


def set_combo(widget: fitz.Widget, value: str):
    set_value(widget, value)


def set_listbox(widget: fitz.Widget, value: str):
    set_value(widget, value)


def widgets_by_name(page: fitz.Page) -> dict:
    """Field name -> list of widgets (a name maps to >1 widget for radio
    groups, exactly 1 for everything else).

    Caller must keep `page` referenced (e.g. a local variable) for as
    long as any returned widget is still being read/updated -- widgets
    hold only a weak reference to their parent page, and letting the
    page get garbage-collected mid-edit turns a radio sibling-unset into
    a raw `ReferenceError` instead of a clean update (hit this directly
    writing tests/test_forms.py; ``forms.widgets_by_name(doc[0])`` inline,
    with no named variable holding the page, was enough to trigger it)."""
    out = {}
    for w in page.widgets():
        out.setdefault(w.field_name, []).append(w)
    return out
