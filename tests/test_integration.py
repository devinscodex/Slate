"""Slice 8 check: one real end-to-end task per feature category, driven
through the actual SlateApp instance (real Tk root, real widgets) rather
than re-testing the already-proven business logic in isolation. Modal
dialogs (simpledialog/messagebox/filedialog) are monkeypatched to return
fixed values -- they'd otherwise block forever waiting for a human, but
the real call sites in slate.py still execute exactly as they would live.
"""
import os
import shutil
import sys
import zipfile

import fitz
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gate  # noqa: E402
import slate  # noqa: E402
import sign  # noqa: E402
import version  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "basic3page.pdf")
REAL_EMBEDDABLE_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"


class _FakeEvent:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def _drag(app, x0, y0, x1, y1):
    app._on_press(_FakeEvent(x0, y0))
    app._on_drag(_FakeEvent(x1, y1))
    app._on_release(_FakeEvent(x1, y1))


def _build_test_epub(path):
    """A minimal, valid, synthetic epub -- generated at test time, same
    "never a real/committed document" discipline as the PDF fixtures
    (DESIGN.md's Fixtures section). Confirmed live (this session, before
    writing any of this slice's code): PyMuPDF opens this unmodified via
    plain fitz.open(), with real page_count/get_toc()/get_text()."""
    container_xml = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    content_opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>Slate Test Book</dc:title><dc:language>en</dc:language>'
        '<dc:identifier id="BookId">urn:uuid:12345678-1234-1234-1234-123456789012</dc:identifier>'
        '</metadata><manifest>'
        '<item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="ch2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '</manifest><spine toc="ncx"><itemref idref="ch1"/><itemref idref="ch2"/></spine></package>'
    )
    chapter1 = (
        '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><title>Chapter One</title></head><body><h1>Chapter One</h1>'
        '<p>This is the needle sentence in chapter one.</p></body></html>'
    )
    chapter2 = (
        '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><title>Chapter Two</title></head><body><h1>Chapter Two</h1>'
        '<p>Nothing special appears in this second chapter.</p></body></html>'
    )
    toc_ncx = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head></head>'
        '<docTitle><text>Slate Test Book</text></docTitle><navMap>'
        '<navPoint id="np1" playOrder="1"><navLabel><text>Chapter One</text></navLabel>'
        '<content src="chapter1.xhtml"/></navPoint>'
        '<navPoint id="np2" playOrder="2"><navLabel><text>Chapter Two</text></navLabel>'
        '<content src="chapter2.xhtml"/></navPoint></navMap></ncx>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container_xml)
        z.writestr("OEBPS/content.opf", content_opf)
        z.writestr("OEBPS/chapter1.xhtml", chapter1)
        z.writestr("OEBPS/chapter2.xhtml", chapter2)
        z.writestr("OEBPS/toc.ncx", toc_ncx)


def _make_app(tmp_path, fixture=FIXTURE):
    path = str(tmp_path / "doc.pdf")
    shutil.copy(fixture, path)
    root = tk.Tk()
    app = slate.SlateApp(root, path)
    return root, app


def test_redact_drag_marks_region_then_apply_removes_content(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("redact")
        # page is 595x842pt at zoom 1.5 -> canvas coords are pt*1.5
        _drag(app, 100, 100, 300, 130)
        assert len(app._pending_redactions) == 1
        page_num, rect = app._pending_redactions[0]
        assert page_num == 0
        # canvas (100,100)-(300,130) at zoom 1.5 -> pdf (66.7,66.7)-(200,86.7)
        assert abs(rect.x0 - 100 / 1.5) < 0.01
        assert abs(rect.y1 - 130 / 1.5) < 0.01

        out = str(tmp_path / "redacted.pdf")
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out)
        monkeypatch.setattr(slate.messagebox, "askyesno", lambda *a, **k: True)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

        app.apply_redactions()
        assert app._pending_redactions == []  # cleared after applying
        assert os.path.exists(out)
        reread = fitz.open(out)
        # the marked region covered "Slate fixture page 1" -- confirm the
        # live app's redact flow actually removed real text, not a no-op
        assert "Slate fixture page 1" not in reread[0].get_text()
        reread.close()
    finally:
        app.doc.close()
        root.destroy()


def test_annotate_highlight_drag_adds_real_annotation(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("annotate:highlight")
        _drag(app, 100, 100, 300, 130)
        annots = list(app.doc[0].annots())
        assert len(annots) == 1
        assert annots[0].type[1] == "Highlight"
    finally:
        app.doc.close()
        root.destroy()


def test_annotate_freetext_click_drag_prompts_and_adds_note(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("annotate:freetext")
        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: "a real note")
        _drag(app, 100, 200, 300, 230)
        annots = list(app.doc[0].annots())
        assert len(annots) == 1
        assert annots[0].type[1] == "FreeText"
        assert annots[0].info.get("content") == "a real note"
    finally:
        app.doc.close()
        root.destroy()


def test_merge_via_menu_command(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        second = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second)
        out = str(tmp_path / "merged.pdf")
        monkeypatch.setattr(
            slate.filedialog, "askopenfilenames", lambda **k: (app.path, second)
        )
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

        app.do_merge()
        assert os.path.exists(out)
        merged = fitz.open(out)
        assert merged.page_count == 6  # 3 pages x 2 copies
        merged.close()
    finally:
        app.doc.close()
        root.destroy()


def test_sign_via_menu_command_produces_valid_signature(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        out = str(tmp_path / "signed.pdf")
        monkeypatch.setattr(slate.messagebox, "askyesno", lambda *a, **k: True)
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

        app.do_sign()
        assert os.path.exists(out)
        assert sign.is_signed(out)
        results = sign.validate(out)
        assert all(r.intact and r.valid for r in results)
    finally:
        app.doc.close()
        root.destroy()


def test_encrypt_via_menu_command_round_trips(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        out = str(tmp_path / "encrypted.pdf")
        answers = iter(["ownerpw", "userpw"])
        monkeypatch.setattr(
            slate.simpledialog, "askstring", lambda *a, **k: next(answers)
        )
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

        app.do_encrypt()
        assert os.path.exists(out)
        import security

        with security.open_with_password(out, "userpw") as pdf:
            assert len(pdf.pages) == 3
    finally:
        app.doc.close()
        root.destroy()


def test_forms_click_fills_text_field(tmp_path, monkeypatch):
    """Reuses the same pikepdf-built form fixture pattern as
    test_forms.py (PyMuPDF can fill an existing text field via a click,
    which is the real v1 feature)."""
    import fitz as _fitz

    form_path = str(tmp_path / "form.pdf")
    doc = _fitz.open()
    page = doc.new_page()
    w = _fitz.Widget()
    w.field_name = "name"
    w.field_type = _fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = _fitz.Rect(72, 72, 300, 100)
    page.add_widget(w)
    doc.save(form_path)
    doc.close()

    root = tk.Tk()
    app = slate.SlateApp(root, form_path)
    try:
        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: "Devin")
        app._set_mode("forms")
        # click inside the widget's rect, scaled by zoom (1.5)
        app._on_press(_FakeEvent(int(80 * 1.5), int(85 * 1.5)))

        out = str(tmp_path / "form_filled.pdf")
        slate.io_pdf.safe_save(app.doc, out)
        reread = _fitz.open(out)
        widgets = list(reread[0].widgets())
        assert widgets[0].field_value == "Devin"
        reread.close()
    finally:
        app.doc.close()
        root.destroy()


def test_scan_document_menu_command_finds_and_marks_ssn(tmp_path, monkeypatch):
    path = str(tmp_path / "doc.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "SSN: 123-45-6789", fontsize=12)
    doc.save(path)
    doc.close()

    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        assert app._pending_redactions == []
        app.do_scan_document()
        # do_scan_document opens a Toplevel with a "mark all" button rather
        # than a monkeypatchable dialog function -- find and click it
        # programmatically the same way a real user would, via its
        # registered Tk command, since there's no simulated mouse click.
        found_button = False
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for widget in child.winfo_children():
                    if isinstance(widget, tk.Button):
                        widget.invoke()
                        found_button = True
        assert found_button, "expected a 'mark all hits' button on a real SSN hit"
        assert len(app._pending_redactions) == 1
        assert app._pending_redactions[0][0] == 0  # page 0
    finally:
        app.doc.close()
        root.destroy()


def test_scan_folder_menu_command_via_real_downloads_style_layout(tmp_path, monkeypatch):
    """Same shape as the real Downloads audit this feature was built
    from: one clean file, one with a labeled account number split across
    lines (the exact layout that caused the original false negative)."""
    clean = tmp_path / "clean.pdf"
    dirty = tmp_path / "dirty.pdf"
    d1 = fitz.open()
    d1.new_page().insert_text((72, 72), "nothing sensitive", fontsize=12)
    d1.save(str(clean))
    d1.close()

    d2 = fitz.open()
    page = d2.new_page()
    page.insert_text((72, 72), "Account Number:", fontsize=12)
    page.insert_text((72, 100), "9825039777", fontsize=12)
    d2.save(str(dirty))
    d2.close()

    doc_path = str(tmp_path / "current.pdf")
    fitz.open(str(clean)).save(doc_path)

    root = tk.Tk()
    app = slate.SlateApp(root, doc_path)
    try:
        monkeypatch.setattr(slate.filedialog, "askdirectory", lambda **k: str(tmp_path))
        app.do_scan_folder()
        found_text = None
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for widget in child.winfo_children():
                    if isinstance(widget, tk.Text):
                        found_text = widget.get("1.0", "end")
        assert found_text is not None
        assert "dirty.pdf" in found_text
        assert "clean.pdf" not in found_text
        assert "account-number" in found_text
    finally:
        app.doc.close()
        root.destroy()


def test_launch_with_no_path_shows_home_screen_not_a_document(tmp_path, monkeypatch):
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        assert app.doc is None
        assert app.home_frame is not None
        assert app._doc_view_built is False
    finally:
        root.destroy()


def test_window_icon_loads_from_branding_without_crashing(tmp_path, monkeypatch):
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        assert app._icon_img is not None
        assert app._icon_img.width() == 256
    finally:
        root.destroy()


def test_home_screen_shows_real_version_and_summary(tmp_path, monkeypatch):
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        labels = [
            w for w in app.home_frame.winfo_children()
        ]
        all_text = []

        def collect(widget):
            if isinstance(widget, tk.Label):
                all_text.append(widget.cget("text"))
            for child in widget.winfo_children():
                collect(child)

        collect(app.home_frame)
        assert any(slate.version.VERSION in t for t in all_text)
        assert any(t == slate.version.SUMMARY for t in all_text)
    finally:
        root.destroy()


def test_open_from_home_screen_then_close_returns_to_home_with_recent_entry(tmp_path, monkeypatch):
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    path = str(tmp_path / "doc.pdf")
    shutil.copy(FIXTURE, path)

    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        assert recent_module.get_recent() == []  # nothing yet

        app._open_document(path)
        assert app.doc is not None
        assert app.home_frame is None
        recent_entries = recent_module.get_recent()
        assert len(recent_entries) == 1
        assert recent_entries[0]["path"] == os.path.abspath(path)

        app.do_close()
        assert app.doc is None
        assert app.home_frame is not None
        # the just-closed file should now show up in the (rebuilt) home screen
        assert recent_module.get_recent()[0]["path"] == os.path.abspath(path)
    finally:
        if app.doc is not None:
            app.doc.close()
        root.destroy()


def test_double_click_recent_entry_opens_correct_file_despite_display_formatting(tmp_path, monkeypatch):
    """The home screen shows 'name — parent dir', not the raw path (a
    UI/UX pass improvement) -- open_selected() looks up the real path by
    LIST INDEX into recent.get_recent(), not by parsing the displayed
    text. Two files with different parent dirs but confusingly similar
    display text is exactly the case that would catch an index/lookup
    mismatch."""
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    dir_a = tmp_path / "alpha"
    dir_b = tmp_path / "beta"
    dir_a.mkdir()
    dir_b.mkdir()
    path_a = str(dir_a / "report.pdf")
    path_b = str(dir_b / "report.pdf")  # same basename as path_a, on purpose
    shutil.copy(FIXTURE, path_a)
    shutil.copy(FIXTURE, path_b)

    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        recent_module.add_recent(path_a)
        recent_module.add_recent(path_b)  # most-recent-first -> [path_b, path_a]
        app._show_home_screen()

        app._recent_listbox.selection_set(1)  # second row -> path_a (the older entry)
        app._open_recent_selected()

        assert app.path == os.path.abspath(path_a)
    finally:
        if app.doc is not None:
            app.doc.close()
        root.destroy()


def test_menu_actions_guard_against_no_document_open(tmp_path, monkeypatch):
    """Real gap this refactor had to close: File>Save/Split/Encrypt/Sign
    etc. used to assume a document was always open (the old code always
    opened one in __init__). Confirm they now guard cleanly instead of
    raising when nothing is open."""
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        # none of these should raise with no document open
        app.save()
        app.do_split()
        app.apply_redactions()
        app.do_scan_document()
        app.do_encrypt()
        app.do_sign()
    finally:
        root.destroy()


def test_toc_panel_reflects_real_outline_and_navigates_on_click(tmp_path, monkeypatch):
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    path = str(tmp_path / "withtoc.pdf")
    doc = fitz.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"page {i}", fontsize=14)
    doc.set_toc([[1, "Intro", 1], [1, "Middle", 2], [1, "End", 3]])
    doc.save(path)
    doc.close()

    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        app.toc_visible.set(True)
        app._toggle_toc_panel()
        top_items = app.toc_tree.get_children()
        titles = [app.toc_tree.item(i, "text") for i in top_items]
        assert titles == ["Intro", "Middle", "End"]

        assert app.viewer.page_num == 0
        app.toc_tree.selection_set(top_items[2])  # "End" -> page index 2
        app._on_toc_select()
        assert app.viewer.page_num == 2
    finally:
        app.doc.close()
        root.destroy()


def test_toc_panel_shows_placeholder_when_no_outline(tmp_path, monkeypatch):
    import recent as recent_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")

    root, app = _make_app(tmp_path)  # basic3page.pdf fixture has no outline
    try:
        app.toc_visible.set(True)
        app._toggle_toc_panel()
        items = app.toc_tree.get_children()
        assert len(items) == 1
        assert "no table of contents" in app.toc_tree.item(items[0], "text").lower()
    finally:
        app.doc.close()
        root.destroy()


# ----------------------------------------------------------------------
# Slice 4: gated text editing, wired end-to-end through the real app
# ----------------------------------------------------------------------

def test_textedit_first_run_sets_passphrase_then_unlocks_mode(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        assert gate.is_passphrase_set() is False
        answers = iter(["a-real-passphrase", "a-real-passphrase"])
        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: next(answers))

        app._start_textedit_mode()
        assert gate.is_passphrase_set() is True
        assert app._textedit_unlocked_this_session is True
        assert app.mode == "textedit"
    finally:
        app.doc.close()
        root.destroy()


def test_textedit_mismatched_new_passphrase_does_not_set_or_unlock(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        answers = iter(["first-try", "does-not-match"])
        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: next(answers))
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

        app._start_textedit_mode()
        assert gate.is_passphrase_set() is False
        assert app._textedit_unlocked_this_session is False
        assert app.mode != "textedit"
    finally:
        app.doc.close()
        root.destroy()


def test_textedit_wrong_passphrase_then_correct_on_existing_gate(tmp_path, monkeypatch):
    root, app = _make_app(tmp_path)
    try:
        gate.set_passphrase("the-real-one")

        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: "wrong-guess")
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
        app._start_textedit_mode()
        assert app._textedit_unlocked_this_session is False
        assert app.mode != "textedit"

        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: "the-real-one")
        app._start_textedit_mode()
        assert app._textedit_unlocked_this_session is True
        assert app.mode == "textedit"
    finally:
        app.doc.close()
        root.destroy()


def test_textedit_click_edits_real_text_and_persists_on_reopen(tmp_path, monkeypatch):
    """Real end-to-end: build a fixture with a genuinely embedded,
    non-subsetted font (same fixture-building pattern as
    test_textedit.py's reusable-tier fixture), click through the real
    canvas handler, and confirm the change actually persisted to disk."""
    path = str(tmp_path / "editable.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile=REAL_EMBEDDABLE_FONT)
    page.insert_text(fitz.Point(72, 100), "original wording here", fontname="F1", fontsize=14)
    doc.save(path)
    doc.close()

    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        gate.set_passphrase("unlock-me")
        app._textedit_unlocked_this_session = True
        app._set_mode("textedit")

        monkeypatch.setattr(slate.simpledialog, "askstring", lambda *a, **k: "replaced wording now")
        z = app.viewer.zoom
        app._on_press(_FakeEvent(int(80 * z), int(95 * z)))

        out = str(tmp_path / "edited_via_app.pdf")
        slate.io_pdf.safe_save(app.doc, out)
        reread = fitz.open(out)
        text = reread[0].get_text()
        assert "replaced wording now" in text
        assert "original wording here" not in text
        reread.close()
    finally:
        app.doc.close()
        root.destroy()


def test_textedit_click_warns_on_substitute_tier_for_basic_fixture(tmp_path, monkeypatch):
    """basic3page.pdf's own font is plain "Helvetica", not embedded -- and
    confirmed absent as a real system font on this dev box (fc-match
    finds no exact "Helvetica" here), so this fixture is naturally
    tier "substitute-needed" with zero extra setup, a real case rather
    than a forced one."""
    root, app = _make_app(tmp_path)
    try:
        gate.set_passphrase("unlock-me")
        app._textedit_unlocked_this_session = True
        app._set_mode("textedit")

        seen_prompt = {}

        def fake_askstring(title, prompt, **kwargs):
            seen_prompt["text"] = prompt
            return "new content here"

        monkeypatch.setattr(slate.simpledialog, "askstring", fake_askstring)
        z = app.viewer.zoom
        app._on_press(_FakeEvent(int(100 * z), int(66 * z)))

        assert "close substitute" in seen_prompt["text"].lower()
    finally:
        app.doc.close()
        root.destroy()


def test_find_next_jumps_to_match_across_pages(tmp_path):
    path = str(tmp_path / "findme.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "nothing here", fontsize=14)
    doc.new_page().insert_text((72, 72), "the needle is here", fontsize=14)
    doc.save(path)
    doc.close()

    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        app._show_find_bar()
        app.find_var.set("needle")
        app._find_next()
        assert app.viewer.page_num == 1
        assert app.find_status.cget("text") == "1/1"
        assert len(app.search_state.matches) == 1
    finally:
        app.doc.close()
        root.destroy()


def test_find_next_wraps_around_multiple_matches(tmp_path):
    path = str(tmp_path / "findme2.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "alpha", fontsize=14)
    doc.new_page().insert_text((72, 72), "alpha again", fontsize=14)
    doc.save(path)
    doc.close()

    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        app._show_find_bar()
        app.find_var.set("alpha")
        app._find_next()
        assert app.viewer.page_num == 0
        app._find_next()
        assert app.viewer.page_num == 1
        app._find_next()  # wraps back to first match
        assert app.viewer.page_num == 0
        app._find_prev()  # wraps the other way
        assert app.viewer.page_num == 1
    finally:
        app.doc.close()
        root.destroy()


def test_find_no_matches_shows_no_matches_status(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._show_find_bar()
        app.find_var.set("zzz-nonexistent-zzz")
        app._find_next()
        assert app.find_status.cget("text") == "no matches"
    finally:
        app.doc.close()
        root.destroy()


def test_slash_key_opens_find_bar_unless_already_typing(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        root.update()
        assert not app.find_frame.winfo_ismapped()
        result = app._kb_open_find()
        root.update()
        assert app.find_frame.winfo_ismapped()
        # not already typing anywhere -- consumes the keypress so a
        # literal "/" doesn't also land on whatever had focus
        assert result == "break"

        # now focus is in the find entry itself -- a literal "/" typed
        # as real search text must NOT be intercepted by this handler
        app._find_entry.focus_set()
        root.update()
        result2 = app._kb_open_find()
        assert result2 is None  # guarded: let the entry receive it normally
    finally:
        app.doc.close()
        root.destroy()


def test_keyboard_jk_navigate_pages_and_gG_jump_to_ends(tmp_path):
    root, app = _make_app(tmp_path)  # basic3page.pdf -- 3 pages
    try:
        app.canvas.focus_set()
        root.update()
        assert app.viewer.page_num == 0
        app._kb_next_page()
        assert app.viewer.page_num == 1
        app._kb_prev_page()
        assert app.viewer.page_num == 0
        app._kb_last_page()
        assert app.viewer.page_num == 2
        app._kb_first_page()
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_keyboard_jk_do_nothing_while_typing_in_an_entry(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._show_find_bar()
        app._find_entry.focus_set()
        root.update()
        assert app.viewer.page_num == 0
        app._kb_next_page()  # guarded -- focus is in the find entry
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


# ----------------------------------------------------------------------
# Slice 2: tabs (multiple open documents in one window)
# ----------------------------------------------------------------------

def test_opening_a_second_document_adds_a_tab_without_closing_the_first(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        first_doc = app.doc
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)

        app._open_document(second_path)

        assert len(app._tabs) == 2
        assert app.doc is not first_doc  # active tab switched to the new one
        assert not first_doc.is_closed  # the first tab's document is still open
        assert app.path == second_path
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_reopening_an_already_open_path_switches_instead_of_duplicating(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert len(app._tabs) == 2

        app._open_document(app.path)  # reopen the currently-active one
        assert len(app._tabs) == 2  # no new tab created

        app._open_document(str(tmp_path / "doc.pdf"))  # reopen the FIRST tab's path
        assert len(app._tabs) == 2
        assert app.path == str(tmp_path / "doc.pdf")  # switched back to it
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_switching_tabs_isolates_mode_and_pending_redactions_and_search(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        first_frame = app._tab_frames[0]
        app._set_mode("redact")
        app._pending_redactions.append((0, fitz.Rect(0, 0, 10, 10)))
        app._show_find_bar()
        app.find_var.set("Slate")
        app._find_next()
        assert len(app.search_state.matches) > 0

        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)  # switches active tab

        # the new tab starts completely clean, unaffected by tab 1's state
        assert app.mode == "view"
        assert app._pending_redactions == []
        assert app.search_state.matches == []

        app._select_tab(first_frame)  # switch back

        assert app.mode == "redact"
        assert len(app._pending_redactions) == 1
        assert len(app.search_state.matches) > 0
        assert app.find_var.get() == "Slate"
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_closing_one_tab_leaves_the_others_open(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert len(app._tabs) == 2
        assert app.path == second_path

        app.do_close()  # closes the active (second) tab

        assert len(app._tabs) == 1
        assert app.doc is not None
        assert app.home_frame is None  # still one tab open, not back at home
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_closing_the_last_tab_returns_to_home_screen(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        assert len(app._tabs) == 1
        app.do_close()
        assert app._tabs == []
        assert app.doc is None
        assert app.home_frame is not None
    finally:
        if app._tabs:
            for t in app._tabs:
                t.doc.close()
        root.destroy()


# ----------------------------------------------------------------------
# Slice 3: ebook formats (epub/mobi/fb2/cbz -- PyMuPDF's own native
# support, zero new dependency), PDF-only menu items gated off
# ----------------------------------------------------------------------

def test_opening_an_epub_renders_real_pages_toc_and_text(tmp_path):
    epub_path = str(tmp_path / "book.epub")
    _build_test_epub(epub_path)

    root = tk.Tk()
    app = slate.SlateApp(root, epub_path)
    try:
        assert app.doc.is_pdf is False
        assert app.viewer.page_count == 2
        assert "Chapter One" in app.page.get_text()
        outline = app.viewer.get_outline()
        assert [title for _level, title, _page in outline] == ["Chapter One", "Chapter Two"]
    finally:
        app.doc.close()
        root.destroy()


def test_pdf_only_menu_items_disabled_for_an_open_ebook(tmp_path):
    epub_path = str(tmp_path / "book.epub")
    _build_test_epub(epub_path)

    root = tk.Tk()
    app = slate.SlateApp(root, epub_path)
    try:
        for label in slate._FILE_PDF_ONLY_LABELS:
            assert app.filem.entrycget(label, "state") == "disabled", label
        for label in slate._EDIT_PDF_ONLY_LABELS:
            assert app.editm.entrycget(label, "state") == "disabled", label
    finally:
        app.doc.close()
        root.destroy()


def test_pdf_only_menu_items_stay_enabled_for_a_real_pdf(tmp_path):
    root, app = _make_app(tmp_path)  # basic3page.pdf -- a real PDF
    try:
        for label in slate._FILE_PDF_ONLY_LABELS:
            assert app.filem.entrycget(label, "state") == "normal", label
        for label in slate._EDIT_PDF_ONLY_LABELS:
            assert app.editm.entrycget(label, "state") == "normal", label
    finally:
        app.doc.close()
        root.destroy()


def test_menu_state_updates_correctly_switching_between_pdf_and_epub_tabs(tmp_path):
    root, app = _make_app(tmp_path)  # tab 1: a real PDF
    try:
        assert app.filem.entrycget("Save", "state") == "normal"

        epub_path = str(tmp_path / "book.epub")
        _build_test_epub(epub_path)
        app._open_document(epub_path)  # tab 2: an epub, becomes active

        assert app.filem.entrycget("Save", "state") == "disabled"
        assert app.editm.entrycget("Redact (drag a region)", "state") == "disabled"

        app._select_tab(app._tab_frames[0])  # back to the PDF tab
        assert app.filem.entrycget("Save", "state") == "normal"
        assert app.editm.entrycget("Redact (drag a region)", "state") == "normal"
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


# ----------------------------------------------------------------------
# Convert: office-doc utilities (PDF <-> markdown/text/images) via the
# real menu commands
# ----------------------------------------------------------------------

def test_export_markdown_menu_command_writes_real_heading_and_body(tmp_path, monkeypatch):
    path = str(tmp_path / "doc.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Report Title", fontsize=24, fontname="helv")
    page.insert_text((72, 100), "A body sentence.", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()

    out = str(tmp_path / "out.md")
    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
        app.do_export_markdown()
        assert os.path.exists(out)
        content = open(out).read()
        assert "# Report Title" in content
        assert "A body sentence." in content
    finally:
        app.doc.close()
        root.destroy()


def test_export_text_menu_command_writes_real_text(tmp_path, monkeypatch):
    out = str(tmp_path / "out.txt")
    root, app = _make_app(tmp_path)  # basic3page.pdf
    try:
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
        app.do_export_text()
        assert os.path.exists(out)
        assert "Slate fixture page 1" in open(out).read()
    finally:
        app.doc.close()
        root.destroy()


def test_export_images_menu_command_writes_one_png_per_page(tmp_path, monkeypatch):
    out_dir = str(tmp_path / "images_out")
    root, app = _make_app(tmp_path)  # basic3page.pdf -- 3 pages
    try:
        monkeypatch.setattr(slate.filedialog, "askdirectory", lambda **k: out_dir)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
        app.do_export_images()
        written = sorted(os.listdir(out_dir))
        assert len(written) == 3
    finally:
        app.doc.close()
        root.destroy()


def test_import_images_menu_command_creates_and_opens_a_new_pdf(tmp_path, monkeypatch):
    from PIL import Image

    img_paths = []
    for i in range(2):
        p = str(tmp_path / f"scan{i}.png")
        Image.new("RGB", (200, 300), (i * 50, 0, 0)).save(p)
        img_paths.append(p)

    out_pdf = str(tmp_path / "combined.pdf")
    root, app = _make_app(tmp_path)
    try:
        original_tab_count = len(app._tabs)
        monkeypatch.setattr(slate.filedialog, "askopenfilenames", lambda **k: tuple(img_paths))
        monkeypatch.setattr(slate.filedialog, "asksaveasfilename", lambda **k: out_pdf)
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

        app.do_import_images()
        assert os.path.exists(out_pdf)
        assert len(app._tabs) == original_tab_count + 1  # opened as a new tab
        assert app.path == out_pdf
        assert app.doc.page_count == 2
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_convert_menu_actions_guard_against_no_document_open(tmp_path, monkeypatch):
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        app.do_export_markdown()
        app.do_export_text()
        app.do_export_images()
    finally:
        root.destroy()


def test_about_dialog_shows_real_version_and_summary(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._show_about()
        found_version = False
        found_summary = False
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for widget in child.winfo_children():
                    if isinstance(widget, tk.Label):
                        text = widget.cget("text")
                        if version.VERSION in text:
                            found_version = True
                        if text == version.SUMMARY:
                            found_summary = True
        assert found_version, "About dialog should show version.VERSION"
        assert found_summary, "About dialog should show version.SUMMARY"
    finally:
        app.doc.close()
        root.destroy()
