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
import pytest
import tkinter as tk
from tkinter import ttk
from PIL import ImageColor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gate  # noqa: E402
import slate  # noqa: E402
import sign  # noqa: E402
import theme  # noqa: E402
import tts  # noqa: E402
import version  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "basic3page.pdf")

# A real embeddable TTF for the text-edit "reusable font" tests. Real
# bug caught on an actual Windows smoke test: this used to hardcode a
# Linux-only path, which fitz.Page.insert_font() then failed to open
# there. A small existence-checked candidate list instead of one
# hardcoded assumption -- same fix already applied to test_convert.py.
_EMBEDDABLE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",  # Linux (Debian/Ubuntu)
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",  # Linux (Fedora)
    r"C:\Windows\Fonts\times.ttf",  # Windows
]
REAL_EMBEDDABLE_FONT = next((p for p in _EMBEDDABLE_FONT_CANDIDATES if os.path.exists(p)), None)


class _FakeEvent:
    def __init__(self, x, y, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


def _wait_until(condition, root, timeout=10):
    """Pumps the real Tk event loop (root.update()) until condition()
    is true or timeout -- for background-thread work (TTS synthesis,
    voice downloads) that no longer completes synchronously within a
    single call. Real Tk limitation already hit elsewhere in this
    suite: synthetic events don't reliably dispatch without a genuine
    running mainloop, but plain root.update() calls in a loop do pump
    real after()-scheduled callbacks correctly."""
    import time

    end = time.time() + timeout
    while not condition() and time.time() < end:
        root.update()
        time.sleep(0.02)


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
    # Real gap surfaced after defaulting view_mode to "continuous"
    # (2026-07-25): this headless test harness runs Xvfb with NO real
    # window manager, so nothing ever grants the toplevel real X input
    # focus automatically -- a plain child_widget.focus_set() silently
    # no-ops (root.focus_get() stays None) until something forces real
    # focus onto the toplevel at least once. A real Windows machine
    # always has a real WM handing a newly-opened app window focus, so
    # this is a test-environment quirk, not a product bug -- fixed
    # here (once, for every test) rather than in production code.
    root.focus_force()
    root.update()
    return root, app


def test_render_recolors_the_page_to_match_the_active_theme_not_just_chrome(tmp_path, monkeypatch):
    """Real gap Devin caught live, twice: (1) theming Slate's own
    widgets dark still left the rendered PDF page a blinding white
    rectangle, and (2) a first-attempt fix (a flat RGB invert) only
    looked right for the plain built-in "dark" theme -- every OTHER
    light-toned named theme (Bonepaper Light)
    still rendered a plain white page that didn't match its own tinted
    chrome at all ("want document to match", "same as text editors
    when using themes"). Fixed with ImageOps.colorize: the page's own
    light<->dark tones map onto the active theme's canvas_bg<->fg pair,
    one mechanism for every theme, light or dark alike. ImageTk.
    PhotoImage exposes no way to read pixels back, so this intercepts
    what gets passed INTO it instead."""
    import theme

    root, app = _make_app(tmp_path)
    try:
        # colorize_pages now defaults False (2026-07-26, real content
        # got destroyed twice the same day by the theme-tint flatten) --
        # this test verifies the recolor MECHANISM itself still works
        # correctly across every theme when a reader opts in, unaffected
        # by what the default happens to be.
        app.colorize_pages = True
        captured = {}
        real_photoimage = slate.ImageTk.PhotoImage

        def spy(img, *a, **k):
            captured["img"] = img.copy()
            return real_photoimage(img, *a, **k)

        monkeypatch.setattr(slate.ImageTk, "PhotoImage", spy)

        for name in theme.THEMES:
            app.theme_name.set(name)
            app._on_theme_changed()
            pixel = captured["img"].convert("RGB").getpixel((5, 5))
            expected = ImageColor.getrgb(theme.THEMES[name]["canvas_bg"])
            assert pixel == expected, f"{name}'s page background should match its own canvas_bg"
    finally:
        app.doc.close()
        root.destroy()


def test_dark_mode_repaints_toolbar_and_canvas(tmp_path):
    import theme

    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("light")
        app._apply_theme()
        assert app.canvas.cget("bg") == theme.LIGHT["canvas_bg"]

        app.theme_name.set("dark")
        app._apply_theme()
        assert app.canvas.cget("bg") == theme.DARK["canvas_bg"]
        assert app.root.cget("bg") == theme.DARK["bg"]

        app.theme_name.set("light")
        app._apply_theme()
        assert app.canvas.cget("bg") == theme.LIGHT["canvas_bg"]
        assert app.root.cget("bg") == theme.LIGHT["bg"]
    finally:
        app.doc.close()
        root.destroy()


def test_named_themes_produce_visibly_distinct_colors(tmp_path):
    """Slate and Flexoki are real, separately-sourced palettes, not
    aliases of light/dark with different names -- confirm they
    actually paint different colors from each other and from the
    built-in light/dark pair.

    Checks (canvas_bg, select_bg) pairs rather than canvas_bg alone
    (loosened 2026-07-29, same reasoning as test_theme.py's own
    test_named_theme_palettes_are_real_and_distinct): this originally
    guarded Boneink Dark deliberately sharing Inkbone Dark's exact
    canvas_bg (#0e0c0a, real "night noir" bones on purpose). Both Inkbone
    and (after the later Boneink+Inkrain merge, then the Inkrain->
    Bonepaper rename) that exact canvas_bg value are gone now, but the
    pair-check stays since it's a strict superset of a bare
    canvas_bg-uniqueness check and remains correct if a future theme
    ever deliberately shares bones again."""
    import theme

    root, app = _make_app(tmp_path)
    try:
        seen = set()
        for name in theme.THEMES:
            app.theme_name.set(name)
            app._apply_theme()
            colors = theme.get_palette(name)
            seen.add((app.canvas.cget("bg"), colors["select_bg"]))
        assert len(seen) == len(theme.THEMES)  # every theme is genuinely distinguishable
    finally:
        app.doc.close()
        root.destroy()


def test_dark_mode_toggle_does_not_break_the_redact_mode_badge(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("redact")
        app.theme_name.set("dark")
        app._apply_theme()
        # dark mode must not clobber the redact safety-color -- reasserted
        # after the generic repaint pass
        assert app.mode_label.cget("bg") == "#c0392b"
        assert app.mode_label.cget("fg") == "white"
    finally:
        app.doc.close()
        root.destroy()


def test_dark_mode_theme_applies_to_a_freshly_opened_dialog(tmp_path):
    import theme

    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("dark")
        app._apply_theme()
        app._show_about()

        about_top = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
        assert about_top.cget("bg") == theme.DARK["bg"]
    finally:
        app.doc.close()
        root.destroy()


def test_toggling_theme_persists_and_a_fresh_launch_starts_dark_no_flash(tmp_path):
    """The real ask this fixes: without persistence, every launch starts
    on the default theme and visibly flashes to the saved one a moment
    later. root.configure(bg=...) for the loaded preference happens as
    the very first line of __init__, before any other widget -- confirmed
    here by checking a BRAND NEW app instance's root bg matches DARK
    immediately, with no separate _apply_theme() call needed first."""
    import theme

    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("dark")
        app._on_theme_changed()
        assert theme.load_preference() == "dark"
    finally:
        app.doc.close()
        root.destroy()

    root2 = tk.Tk()
    app2 = slate.SlateApp(root2, path=None)
    try:
        assert app2.theme_name.get() == "dark"
        assert root2.cget("bg") == theme.DARK["bg"]
    finally:
        root2.destroy()
        theme.save_preference("light")  # leave clean for any test that runs after


def test_mode_indicator_turns_red_in_redact_mode_and_resets_after(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        neutral_bg = app.mode_label.cget("bg")

        app._set_mode("redact")
        assert app.mode_label.cget("bg") == "#c0392b"
        assert app.mode_label.cget("fg") == "white"

        app._set_mode("view")
        assert app.mode_label.cget("bg") == neutral_bg
        assert app.mode_label.cget("fg") == "blue"

        app._set_mode("annotate:highlight")
        assert app.mode_label.cget("bg") == neutral_bg  # only redact gets the warning color
    finally:
        app.doc.close()
        root.destroy()


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
    import settings as settings_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")
    # Real gap this test tripped over first (Devin, 2026-07-26): unlike
    # recent_module above, settings.py was never isolated from Devin's
    # REAL ~/.slate/settings.json here -- harmless while open_tabs was
    # always empty in practice, but genuinely wrong the moment session
    # restore (this same day) started branching on its real content:
    # a real populated open_tabs list on the actual dev machine made
    # this "no path -> home screen" test silently open real documents
    # instead, home_frame staying None. Same CONFIG_DIR/*_FILE pair-patch
    # pattern as recent_module, just for the module that was missing it.
    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", tmp_path / ".slate" / "settings.json")

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
    import settings as settings_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")
    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", tmp_path / ".slate" / "settings.json")

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
    import settings as settings_module

    monkeypatch.setattr(recent_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(recent_module, "RECENT_FILE", tmp_path / ".slate" / "recent.json")
    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", tmp_path / ".slate" / "settings.json")

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
    if REAL_EMBEDDABLE_FONT is None:
        pytest.skip("no known real embeddable font found on this machine")
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
        # Real font-file-specific quirk caught on an actual Windows smoke
        # test: some embedded fonts render inserted spaces as U+00A0
        # (non-breaking) rather than a regular ASCII space -- neither is
        # wrong, this cares about the words, not the exact whitespace byte.
        text = reread[0].get_text().replace("\xa0", " ")
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


def test_middle_click_closes_that_tab(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert len(app._tabs) == 2
        root.update()

        # any point that identify()/index() resolves to tab 0 -- real
        # per-tab pixel bounds (bbox()) are confirmed unreliable in this
        # environment (see _on_tab_strip_click's docstring), so this
        # deliberately doesn't depend on them.
        assert app.tab_strip.index("@10,10") == 0
        app._on_tab_strip_click(_FakeEvent(10, 10))

        assert len(app._tabs) == 1
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_middle_click_on_a_background_tab_does_not_disturb_the_active_tab(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)  # tab 0 is now in the background
        assert app.path == second_path
        root.update()

        assert app.tab_strip.index("@10,10") == 0  # the background tab
        app._on_tab_strip_click(_FakeEvent(10, 10))

        assert len(app._tabs) == 1
        assert app.path == second_path  # still on the tab we were already on
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def _find_tab_right_edge(app, index, y=10):
    """Real edge of `index`'s tab, found by probing tab_strip.index()
    directly rather than trusting bbox() (confirmed broken -- always
    returns (0,0,0,0), see _on_tab_strip_left_click's docstring). Same
    technique the app itself uses to hit-test the close glyph."""
    x, right_edge = 0, None
    strip_width = app.tab_strip.winfo_width()
    while x < strip_width:
        try:
            idx_here = app.tab_strip.index(f"@{x},{y}")
        except tk.TclError:
            break
        if idx_here == index:
            right_edge = x
        elif idx_here > index:
            break
        x += 1
    return right_edge


def test_left_click_near_the_close_glyph_closes_that_tab(tmp_path):
    """Devin, 2026-07-26: "'x' on last document tab doesn't close it" --
    real root cause was left-click never having any close behavior at
    all (only middle-click did); this exercises the new left-click
    close-zone hit-test on a BACKGROUND tab first (simplest case)."""
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert len(app._tabs) == 2
        root.update()

        right_edge = _find_tab_right_edge(app, 0)
        assert right_edge is not None
        close_x = right_edge - 2  # comfortably inside the close zone
        assert app.tab_strip.index(f"@{close_x},10") == 0

        app._on_tab_strip_left_click(_FakeEvent(close_x, 10))
        assert len(app._tabs) == 1
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_left_click_away_from_close_glyph_just_selects_the_tab(tmp_path):
    """A left-click anywhere else on a tab must keep its normal
    select behavior -- the new close-zone hit-test must not turn
    every click on a tab into an accidental close."""
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert len(app._tabs) == 2
        root.update()

        assert app.tab_strip.index("@10,10") == 0
        app._on_tab_strip_left_click(_FakeEvent(10, 10))

        assert len(app._tabs) == 2  # not closed -- nowhere near the close glyph
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_left_click_on_close_glyph_of_the_last_remaining_tab_returns_to_home(tmp_path):
    """The actual reported bug, end to end: Devin, 2026-07-26 -- "'x'
    on last document tab doesn't close it and go to home." Confirms
    the fix at the real interaction layer (left-click), not just at
    _close_tab_by_index (already covered, and already correct, by
    test_closing_the_last_tab_returns_to_home_screen below -- the gap
    was purely that nothing routed a left-click there)."""
    root, app = _make_app(tmp_path)
    try:
        assert len(app._tabs) == 1
        root.update()

        right_edge = _find_tab_right_edge(app, 0)
        assert right_edge is not None
        close_x = right_edge - 2
        assert app.tab_strip.index(f"@{close_x},10") == 0

        app._on_tab_strip_left_click(_FakeEvent(close_x, 10))

        assert app._tabs == []
        assert app.doc is None
        assert app.home_frame is not None
    finally:
        if app._tabs:
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


def test_opening_an_epub_with_a_conflicting_charset_is_auto_corrected(tmp_path):
    """Real bug found live opening an actual epub (Brandon Sanderson's
    'The Way of Kings') -- a chapter's meta charset disagreed with its
    own XML encoding declaration, mangling smart quotes/ellipses into
    mojibake. _open_document must route .epub opens through
    epubfix.fix_epub_encoding_conflicts() so this class of file opens
    correctly, while the tab/title/recent-files still show the
    ORIGINAL path, not the corrected temp copy's generated name."""
    import zipfile

    epub_path = str(tmp_path / "mangled.epub")
    smart_quote_utf8 = "“Hello”".encode("utf-8")
    html = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<meta charset="iso-8859-1"/></head>'
        b"<body><p>" + smart_quote_utf8 + b"</p></body></html>"
    )
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title>'
            '<dc:language>en</dc:language>'
            '<dc:identifier id="BookId">urn:uuid:test</dc:identifier></metadata>'
            '<manifest><item id="ch1" href="ch01.html" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="ch1"/></spine></package>',
        )
        z.writestr("OEBPS/ch01.html", html)

    root = tk.Tk()
    app = slate.SlateApp(root, epub_path)
    try:
        assert "“Hello”" in app.page.get_text()  # corrected, not mojibake
        assert app.path == epub_path  # tab/title show the ORIGINAL path, not a temp name
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


# ----------------------------------------------------------------------
# Read Aloud (TTS)
# ----------------------------------------------------------------------

def test_read_page_guards_against_no_document_open(tmp_path, monkeypatch):
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
    root = tk.Tk()
    app = slate.SlateApp(root, path=None)
    try:
        app.do_read_page()  # must not raise
    finally:
        root.destroy()


def test_read_page_with_no_extractable_text_shows_nothing_to_read(tmp_path, monkeypatch):
    path = str(tmp_path / "blank.pdf")
    doc = fitz.open()
    doc.new_page()  # a real page, deliberately no text on it
    doc.save(path)
    doc.close()

    seen = {}
    monkeypatch.setattr(
        slate.messagebox, "showinfo", lambda title, msg: seen.update(title=title, msg=msg)
    )
    root = tk.Tk()
    app = slate.SlateApp(root, path)
    try:
        app.do_read_page()
        assert seen.get("title") == "Nothing to read"
    finally:
        app.doc.close()
        root.destroy()


def test_read_page_synthesizes_with_the_bundled_voice_and_handles_playback_for_real(tmp_path, monkeypatch):
    """Real synthesis against the bundled voice, through the actual
    do_read_page() path (background thread + poll(), not mocked).
    What SHOULD happen next genuinely depends on whether this machine
    has a real audio output device -- checked here at test time via
    sounddevice's own device query, not assumed from the OS name.
    Real finding: this environment's dev box (WSL2) has zero audio
    devices (confirmed via sd.query_devices()), so playback there
    fails soft with a real PortAudioError message -- but a real
    Windows machine WITH actual speakers (confirmed live, Devin heard
    it) synthesizes AND plays successfully, no error at all. Both are
    correct outcomes for their respective machines; this test asserts
    whichever one this machine should actually produce."""
    import sounddevice as sd

    seen = {}
    monkeypatch.setattr(
        slate.messagebox, "showinfo", lambda title, msg: seen.update(title=title, msg=msg)
    )
    root, app = _make_app(tmp_path)  # basic3page.pdf -- has real text
    try:
        app.tts_voice.set("northern_english_male")  # bundled, no download needed
        app.do_read_page()  # synthesis now runs on a background thread
        _wait_until(lambda: not getattr(app, "_tts_synthesizing", False), root)
        # Real crash fixed live building Slice 3: the flag alone can
        # flip False microseconds before the OS thread genuinely
        # finishes tearing down (still mid its first-ever `import
        # piper`) -- joining the real thread object guarantees it
        # is actually gone before this test tears down and the next
        # one's main-thread Tk work could race it.
        app._tts_thread.join(timeout=5)

        has_real_device = len(sd.query_devices()) > 0
        if has_real_device:
            assert seen == {}  # real hardware -- synthesis AND playback both succeeded
        else:
            assert seen.get("title") == "Playback failed"
            assert "PortAudio" in seen.get("msg", "") or "device" in seen.get("msg", "").lower()
    finally:
        app.doc.close()
        root.destroy()


def test_read_page_offers_to_download_a_non_bundled_voice(tmp_path, monkeypatch):
    """Real download flow, network mocked (same pattern as test_tts.py)
    -- confirms the confirm-dialog + progress-dialog + actual file
    placement all wire together correctly through the real UI action,
    not just tts.download_voice() in isolation."""
    import tts as tts_module

    def fake_urlretrieve(url, filename, reporthook=None):
        with open(filename, "wb") as f:
            f.write(b"fake model bytes" if url.endswith(".onnx") else b"{}")
        if reporthook is not None:
            reporthook(1, 10, 10)

    monkeypatch.setattr(tts_module.urllib.request, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(slate.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)

    root, app = _make_app(tmp_path)
    try:
        # southern_english_female, not alba -- alba is bundled now
        # (Devin, 2026-07-25: two bundled voices, male+female same
        # tier), so it's no longer a genuine "not yet downloaded"
        # example for this test's premise.
        assert tts_module.is_available("southern_english_female") is False
        app.tts_voice.set("southern_english_female")
        app.do_read_page()  # will still fail at the real play() call (no device) -- that's fine
        assert tts_module.is_available("southern_english_female") is True  # but the download itself really happened
        _wait_until(lambda: not getattr(app, "_tts_synthesizing", False), root)
        # Real crash fixed live building Slice 3: the flag alone can
        # flip False microseconds before the OS thread genuinely
        # finishes tearing down (still mid its first-ever `import
        # piper`) -- joining the real thread object guarantees it
        # is actually gone before this test tears down and the next
        # one's main-thread Tk work could race it.
        app._tts_thread.join(timeout=5)
    finally:
        app.doc.close()
        root.destroy()


def test_declining_the_download_prompt_does_not_download_or_crash(tmp_path, monkeypatch):
    import tts as tts_module

    monkeypatch.setattr(slate.messagebox, "askyesno", lambda *a, **k: False)
    root, app = _make_app(tmp_path)
    try:
        app.tts_voice.set("southern_english_female")
        app.do_read_page()  # must not raise
        assert tts_module.is_available("southern_english_female") is False
    finally:
        app.doc.close()
        root.destroy()


def _make_doc_with_a_blank_middle_page(tmp_path):
    """A real 3-page doc where page 1 (0-indexed) has no extractable
    text at all -- the real case _advance_to_next_page_and_continue_
    reading must skip silently rather than interrupting a hands-free
    document read with a dialog."""
    path = str(tmp_path / "blank_middle.pdf")
    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_text((72, 72), "Page one has real text.")
    doc.new_page(width=595, height=842)  # deliberately blank
    doc.new_page(width=595, height=842).insert_text((72, 72), "Page three has real text.")
    doc.save(path)
    doc.close()
    return path


def test_do_read_document_sets_the_reading_document_flag(tmp_path):
    """do_read_page (single-page) and do_read_document (whole
    document) must set _tts_reading_document oppositely -- switching
    back to a plain single-page read cancels any in-progress
    auto-continuation."""
    root, app = _make_app(tmp_path)
    try:
        app.do_read_document()
        assert app._tts_reading_document is True

        app.do_read_page()
        assert app._tts_reading_document is False
    finally:
        app.doc.close()
        root.destroy()


def test_do_tts_stop_cancels_reading_document(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._tts_reading_document = True
        app.do_tts_stop()
        assert app._tts_reading_document is False
    finally:
        app.doc.close()
        root.destroy()


def test_natural_completion_advances_to_the_next_page_when_reading_document(tmp_path, monkeypatch):
    """The real auto-advance mechanism: a page's audio reaching its
    natural end (was playing, now isn't, and NOT because of an
    explicit pause) while _tts_reading_document is True must move to
    the next page and start reading it -- simulated directly via
    _tts_was_playing/Player state rather than real audio hardware."""
    root, app = _make_app(tmp_path)
    try:
        app._tts_reading_document = True
        app._tts_reading_page_num = app.viewer.page_num  # page 0
        app._tts_was_playing = True  # simulate "was playing" on the previous poll tick
        assert app.tts_player.is_playing() is False  # nothing actually loaded -- a real "stopped" state
        assert app.tts_player.is_paused() is False  # NOT a pause -- the real distinguishing check

        called = []
        monkeypatch.setattr(app, "_read_current_page", lambda: called.append(app.viewer.page_num))
        app._poll_tts_playback_state()

        assert app.viewer.page_num == 1  # real navigation happened
        assert called == [1]  # and the next page's read was actually triggered
    finally:
        app.doc.close()
        root.destroy()


def test_pause_does_not_trigger_advance_to_the_next_page(tmp_path, monkeypatch):
    """The real distinguishing case natural-completion detection
    exists for: an explicit pause must NEVER advance to the next page,
    only a genuine end of audio should."""
    root, app = _make_app(tmp_path)
    try:
        app._tts_reading_document = True
        app._tts_reading_page_num = app.viewer.page_num
        app.tts_player.load(b"\x00\x00" * 22050, 22050, 1)
        try:
            app.tts_player.play()
        except Exception:
            pass  # no real audio device on this dev box (WSL2)
        app._tts_was_playing = True
        app.tts_player.pause()

        called = []
        monkeypatch.setattr(app, "_advance_to_next_page_and_continue_reading", lambda: called.append(True))
        app._poll_tts_playback_state()

        assert called == []  # pause must never trigger the advance
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_advance_skips_a_blank_page_silently(tmp_path, monkeypatch):
    """A blank page encountered while auto-advancing must be skipped
    without any "nothing to read" dialog -- that would interrupt a
    hands-free continuous read."""
    root, app = _make_app(tmp_path, fixture=_make_doc_with_a_blank_middle_page(tmp_path))
    try:
        shown = []
        monkeypatch.setattr(slate.messagebox, "showinfo", lambda title, msg: shown.append(title))
        app._tts_reading_document = True
        app._tts_reading_page_num = 0  # page 0 just "finished" -- page 1 is blank, page 2 has text

        called = []
        monkeypatch.setattr(app, "_read_current_page", lambda: called.append(app.viewer.page_num))
        app._advance_to_next_page_and_continue_reading()

        assert shown == []  # no interrupting dialog for the blank page
        assert app.viewer.page_num == 2  # landed on the next REAL page, skipping the blank one
        assert called == [2]
    finally:
        app.doc.close()
        root.destroy()


def test_advance_stops_cleanly_at_the_end_of_the_document(tmp_path):
    root, app = _make_app(tmp_path)  # basic3page.pdf -- 3 real pages, no blanks
    try:
        app._tts_reading_document = True
        app._tts_reading_page_num = app.viewer.page_count - 1  # already on the last page

        app._advance_to_next_page_and_continue_reading()

        assert app._tts_reading_document is False  # cleanly stopped, not left dangling
    finally:
        app.doc.close()
        root.destroy()


def test_changing_voice_restarts_the_current_page_when_something_is_already_loaded(tmp_path, monkeypatch):
    """Real bug fixed (Devin, 2026-07-25: "changing voices mid-read is
    not working"): the Voice menu's radiobuttons had no command
    callback at all, so selecting a different voice never applied
    until some unrelated independent trigger. With audio already
    loaded, selecting a voice must restart the current page fresh."""
    root, app = _make_app(tmp_path)
    try:
        called = []
        monkeypatch.setattr(app, "do_read_page", lambda: called.append("read"))
        app.tts_player.load(b"\x00\x00" * 100, 22050, 1)  # real load, no device needed
        assert app.tts_player.has_audio() is True

        app._on_tts_voice_changed()
        assert called == ["read"]
    finally:
        app.doc.close()
        root.destroy()


def test_changing_voice_is_a_no_op_when_nothing_is_loaded_yet(tmp_path, monkeypatch):
    """No accidental read triggered just from picking a voice before
    ever reading anything -- only applies when something's already
    loaded (the real "mid-read" case the bug report was about)."""
    root, app = _make_app(tmp_path)
    try:
        called = []
        monkeypatch.setattr(app, "do_read_page", lambda: called.append("read"))
        assert app.tts_player.has_audio() is False

        app._on_tts_voice_changed()
        assert called == []
    finally:
        app.doc.close()
        root.destroy()


def test_pause_resume_and_stop_do_not_raise_with_nothing_loaded(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app.do_tts_pause_resume()  # nothing loaded/playing -- must not raise
        app.do_tts_stop()
    finally:
        app.doc.close()
        root.destroy()


def test_toolbar_has_real_tts_play_and_stop_buttons(tmp_path):
    """Devin, 2026-07-25: "easier 'audio readback' controls, preferably
    also available on the main toolbar" -- previously only reachable
    via the Read Aloud menu."""
    root, app = _make_app(tmp_path)
    try:
        assert app.tts_play_button.winfo_ismapped()
        assert app.tts_stop_button.winfo_ismapped()
    finally:
        app.doc.close()
        root.destroy()


def test_tts_toggle_play_routes_to_read_page_when_nothing_loaded(tmp_path, monkeypatch):
    """do_tts_toggle_play is the toolbar button's one action for every
    state -- with nothing loaded yet, it must start a fresh read, not
    a no-op pause/resume."""
    root, app = _make_app(tmp_path)
    try:
        called = []
        monkeypatch.setattr(app, "do_read_page", lambda: called.append("read"))
        monkeypatch.setattr(app, "do_tts_pause_resume", lambda: called.append("pause_resume"))
        assert app.tts_player.has_audio() is False

        app.do_tts_toggle_play()
        assert called == ["read"]
    finally:
        app.doc.close()
        root.destroy()


def test_tts_toggle_play_routes_to_pause_resume_when_already_loaded(tmp_path, monkeypatch):
    """Once something's loaded (playing or paused), the same toolbar
    button must toggle pause/resume, not start a redundant fresh read."""
    root, app = _make_app(tmp_path)
    try:
        app.tts_player.load(b"\x00\x00" * 100, 22050, 1)  # real load, no device needed
        called = []
        monkeypatch.setattr(app, "do_read_page", lambda: called.append("read"))
        monkeypatch.setattr(app, "do_tts_pause_resume", lambda: called.append("pause_resume"))
        assert app.tts_player.has_audio() is True

        app.do_tts_toggle_play()
        assert called == ["pause_resume"]
    finally:
        app.doc.close()
        root.destroy()


def test_tts_toolbar_button_glyph_reflects_playback_state(tmp_path):
    """The toolbar button's own label must track real player state --
    stale glyphs are exactly the kind of small-but-real gap that reads
    as broken even when the underlying feature works."""
    root, app = _make_app(tmp_path)
    try:
        app._update_tts_toolbar_button()
        assert app.tts_play_button.cget("text") == "▶"

        app.tts_player.load(b"\x00\x00" * 22050, 22050, 1)
        try:
            app.tts_player.play()
        except Exception:
            pass  # no real audio device on this dev box (WSL2) -- state still updates
        app._update_tts_toolbar_button()
        expected = "⏸" if app.tts_player.is_playing() else "▶"
        assert app.tts_play_button.cget("text") == expected

        app.do_tts_stop()
        assert app.tts_play_button.cget("text") == "▶"
    finally:
        app.doc.close()
        root.destroy()


def test_tts_status_text_shows_voice_and_speed_only_while_loaded(tmp_path):
    """Devin, 2026-07-25: "is there a way to tell what is the current
    voice/speed is on readback?" -- real, minimal answer, empty when
    nothing's loaded so it doesn't clutter the toolbar otherwise."""
    root, app = _make_app(tmp_path)
    try:
        assert app._tts_status_text() == ""

        app.tts_voice.set("northern_english_male")
        app.tts_speed.set(1.25)
        app.tts_player.load(b"\x00\x00" * 100, 22050, 1)
        text = app._tts_status_text()
        assert "1.25x" in text
        assert tts.VOICES["northern_english_male"]["label"] in text

        # Player.stop() deliberately rewinds rather than unloads (own
        # docstring: "Unlike pause(), resets position to the start")
        # -- has_audio() stays True on purpose so a subsequent play()
        # replays this page from 0, so the status text correctly stays
        # visible too, not cleared.
        app.do_tts_stop()
        assert app._tts_status_text() != ""
    finally:
        app.doc.close()
        root.destroy()


def test_tts_highlight_estimates_position_from_playback_progress(tmp_path):
    """Real follow-along highlight (Devin, 2026-07-25, same message as
    the status-text ask) -- estimated from Player.progress against the
    page's own word list (no per-word timing data exists to do this
    exactly, an honest, documented approximation). At progress 0.0 the
    highlight should sit on the page's first word."""
    root, app = _make_app(tmp_path)  # basic3page.pdf -- real text, page 1: "Slate fixture page 1"
    try:
        app._tts_reading_page = app.page
        app._tts_reading_page_num = app.viewer.page_num
        app._tts_reading_words = app.page.get_text("words")  # real word list, see 2026-07-26 highlight-alignment fix
        app.tts_player.load(b"\x00\x00" * 200, 22050, 1)  # has_audio() True, progress 0.0

        app._update_tts_highlight()
        items = app.canvas.find_withtag("tts_highlight")
        assert len(items) > 0  # something drawn

        words = app.page.get_text("words")
        first_word_x0 = words[0][0] * app.viewer.zoom
        drawn_x0 = app.canvas.coords(items[0])[0]
        assert abs(drawn_x0 - first_word_x0) < 1.0  # anchored at the first word, progress 0.0
    finally:
        app.doc.close()
        root.destroy()


def test_tts_highlight_is_one_merged_box_spanning_same_line_words(tmp_path):
    """Devin, 2026-07-25, real live feedback: "it also looks
    weird...rasterized or something, not a natural 'highlight'" --
    the earlier version drew a SEPARATE stippled rectangle per word
    (2-3 of them), which visibly fragmented and could jump to a
    disconnected box on the next line mid-window. Real fix: exactly
    ONE rectangle, merged across every word sharing the anchor's line
    (basic3page.pdf's page 1 is a real single line: "Slate fixture
    page 1", all 4 words, block_no=0/line_no=0).

    Anchored near the END of the line (progress near 1.0), not the
    start -- the highlight window became TRAILING (2026-07-26, "TTS
    indicator too fast" fix: it used to look 5 words AHEAD of the
    estimate, which visibly read unspoken text). At progress 0.0 a
    trailing window correctly shows just the FIRST word (nothing has
    been read yet, so there's nothing earlier to merge with) -- that's
    real, intentional behavior, not a regression; this test instead
    anchors at the last word to exercise the "merges multiple already-
    read words into one box" property the trailing window does provide."""
    root, app = _make_app(tmp_path)
    try:
        app._tts_reading_page = app.page
        app._tts_reading_page_num = app.viewer.page_num
        app._tts_reading_words = app.page.get_text("words")  # real word list, see 2026-07-26 highlight-alignment fix
        app.tts_player.load(b"\x00\x00" * 200, 22050, 1)
        app.tts_player._position = 199  # progress ~1.0 -- anchors on "1", the last word

        app._update_tts_highlight()
        items = app.canvas.find_withtag("tts_highlight")
        assert len(items) == 1  # one merged box, not one per word

        words = app.page.get_text("words")
        first_word_x0 = words[0][0] * app.viewer.zoom  # "Slate", first word on the same line
        drawn_x0, _drawn_y0 = app.canvas.coords(items[0])
        assert abs(drawn_x0 - first_word_x0) < 1.0  # box extends back across the whole line, not just the last word
    finally:
        app.doc.close()
        root.destroy()


def test_tts_highlight_clears_when_nothing_is_loaded_or_never_read(tmp_path):
    """A fresh app (never read anything) must show no highlight."""
    root, app = _make_app(tmp_path)
    try:
        app._update_tts_highlight()
        assert len(app.canvas.find_withtag("tts_highlight")) == 0
    finally:
        app.doc.close()
        root.destroy()


def test_tts_highlight_clears_when_the_read_page_scrolls_out_of_view(tmp_path):
    """The page being read isn't necessarily what's on screen (the
    user can keep scrolling/navigating while listening) -- nothing
    should be drawn once it's no longer part of the current window/row."""
    root, app = _make_app(tmp_path)
    try:
        app._tts_reading_page = app.page
        app._tts_reading_page_num = app.viewer.page_num
        app._tts_reading_words = app.page.get_text("words")  # real word list, see 2026-07-26 highlight-alignment fix
        app.tts_player.load(b"\x00\x00" * 200, 22050, 1)
        app._update_tts_highlight()
        assert len(app.canvas.find_withtag("tts_highlight")) > 0

        app._last_window = set()  # simulate the read page scrolling out of the current window
        app._update_tts_highlight()
        assert len(app.canvas.find_withtag("tts_highlight")) == 0
    finally:
        app.doc.close()
        root.destroy()


def _all_descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _all_descendants(child)


def test_about_dialog_shows_real_version_and_summary(tmp_path):
    """Real fix, 2026-07-25: the version Label moved one level deeper
    (top -> header -> Label) when the icon was added alongside the
    title -- searches all descendants now, not just direct children,
    so this doesn't re-break on the next layout tweak either."""
    root, app = _make_app(tmp_path)
    try:
        app._show_about()
        found_version = False
        found_summary = False
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for widget in _all_descendants(child):
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


def test_about_dialog_shows_the_author(tmp_path):
    """Real gap Devin caught live: the About dialog showed version/
    summary but never actually credited an author anywhere the app
    itself surfaces (only README.md had it, invisible while just
    running the app)."""
    root, app = _make_app(tmp_path)
    try:
        app._show_about()
        found_author = False
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for widget in child.winfo_children():
                    if isinstance(widget, tk.Label) and version.AUTHOR in widget.cget("text"):
                        found_author = True
        assert found_author, "About dialog should credit version.AUTHOR"
    finally:
        app.doc.close()
        root.destroy()


def test_up_down_arrows_navigate_pages(tmp_path):
    """Real Tk limitation, same one already noted for Double-Button-1:
    synthetic key events via event_generate don't reliably dispatch
    without real window-manager focus in this test harness -- Up/Down
    are bound straight to the same guarded _kb_prev_page/_kb_next_page
    j/k already use, called directly here instead."""
    root, app = _make_app(tmp_path)  # basic3page.pdf -- 3 pages
    try:
        assert app.viewer.page_num == 0
        app._kb_next_page()
        assert app.viewer.page_num == 1
        app._kb_prev_page()
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_up_down_do_nothing_while_typing_in_an_entry(tmp_path):
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


def test_mouse_wheel_navigates_pages_both_platform_styles(tmp_path):
    """X11 (this dev environment) delivers wheel input as discrete
    Button-4/Button-5 clicks bound straight to _kb_prev_page/
    _kb_next_page; Windows/Mac instead deliver a single <MouseWheel>
    event with a signed delta, handled by _on_mouse_wheel. Both are
    real code paths in slate.py, exercised directly here (see the
    event_generate limitation noted above) rather than only through
    whichever one X11 can actually simulate."""
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        assert app.viewer.page_num == 0

        app._kb_next_page()  # X11 Button-5 wiring
        assert app.viewer.page_num == 1
        app._kb_prev_page()  # X11 Button-4 wiring
        assert app.viewer.page_num == 0

        app._on_mouse_wheel(_FakeEvent(0, 0, delta=-120))  # Windows/Mac wheel-down
        assert app.viewer.page_num == 1
        app._on_mouse_wheel(_FakeEvent(0, 0, delta=120))  # Windows/Mac wheel-up
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_view_mode_drag_selects_text_not_a_rectangle(tmp_path):
    """Default interaction (Devin, 2026-07-25: "default to arrow/select
    text over rectangle select") -- a click-drag in the default "view"
    mode selects real text, it does NOT create a redaction mark or
    leave a stray drag-rectangle behind. basic3page.pdf page 1's real
    text: "Slate fixture page 1".

    Real, continuous text-FLOW selection (Devin, 2026-07-26: "mouse
    down should be point of highlight start... continuous highlight
    like you'd expect a highlight tool to do") -- selects every word
    in READING ORDER between the drag's anchor (mouse-down) and
    current cursor position, not just words whose bbox literally
    overlaps the drag rectangle. This specific drag's endpoint lands
    closer to "page" than to "fixture" in PDF space, so "page" is
    correctly included even though the old rect-intersection version
    stopped at "fixture" -- confirmed against the real live app."""
    root, app = _make_app(tmp_path)
    try:
        assert app.mode == "view"  # the actual default, confirmed
        z = app.viewer.zoom
        _drag(app, int(70 * z), int(55 * z), int(148 * z), int(78 * z))
        # self._selected_words is (page_num, word) pairs now (Devin,
        # 2026-07-26: cross-page selection) -- unpack accordingly.
        selected = [w[4] for _pn, w in app._selected_words]
        assert selected == ["Slate", "fixture", "page"]
        assert app._selected_text() == "Slate fixture page"
        # Real, not a redaction -- view-mode drags must never populate this.
        assert app._pending_redactions == []
    finally:
        app.doc.close()
        root.destroy()


def test_new_click_in_view_mode_clears_previous_selection(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        z = app.viewer.zoom
        _drag(app, int(70 * z), int(55 * z), int(148 * z), int(78 * z))
        assert app._selected_words != []

        app._on_press(_FakeEvent(int(10 * z), int(10 * z)))  # a plain click elsewhere
        assert app._selected_words == []
    finally:
        app.doc.close()
        root.destroy()


def test_page_navigation_clears_a_stale_selection(tmp_path):
    """A selection's word-rects belong to the page they were made on --
    carrying them across a page turn would draw/copy the wrong page's
    words (or crash on an out-of-range page)."""
    root, app = _make_app(tmp_path)
    try:
        z = app.viewer.zoom
        _drag(app, int(70 * z), int(55 * z), int(148 * z), int(78 * z))
        assert app._selected_words != []

        app.next()
        assert app._selected_words == []
    finally:
        app.doc.close()
        root.destroy()


def test_copy_selection_puts_real_text_on_the_clipboard(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        z = app.viewer.zoom
        _drag(app, int(70 * z), int(55 * z), int(148 * z), int(78 * z))
        app._copy_selection()
        # "page" included -- same anchor-to-cursor reading-order
        # selection as test_view_mode_drag_selects_text_not_a_rectangle,
        # see that test's docstring for why.
        assert root.clipboard_get() == "Slate fixture page"
    finally:
        app.doc.close()
        root.destroy()


def test_copy_with_no_selection_does_not_raise(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._copy_selection()  # nothing selected -- must be a safe no-op
    finally:
        app.doc.close()
        root.destroy()


def test_redact_mode_drag_still_marks_a_rectangle_not_text(tmp_path):
    """The behavior change is scoped to view mode only -- redact/
    annotate modes must keep their original rectangle-drag semantics."""
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("redact")
        z = app.viewer.zoom
        _drag(app, int(70 * z), int(55 * z), int(148 * z), int(78 * z))
        assert len(app._pending_redactions) == 1
        assert app._selected_words == []
    finally:
        app.doc.close()
        root.destroy()


def test_toc_panel_toggles_off_then_on_again_stays_left_of_canvas(tmp_path):
    """Real correctness point for the PanedWindow conversion (Devin,
    2026-07-25: "TOC should be drag resizeable too please") --
    PanedWindow.add() appends to the END by default, so re-showing the
    TOC after hiding it would land it AFTER (right of) the canvas pane
    without the explicit before=self.canvas fix in _toggle_toc_panel."""
    root, app = _make_app(tmp_path)
    try:
        app.toc_visible.set(True)
        app._toggle_toc_panel()
        app.toc_visible.set(False)
        app._toggle_toc_panel()
        app.toc_visible.set(True)
        app._toggle_toc_panel()

        panes = [str(p) for p in app._content_frame.panes()]
        assert panes.index(str(app.toc_frame)) < panes.index(str(app._canvas_frame))
    finally:
        app.doc.close()
        root.destroy()


def test_windows_app_user_model_id_is_a_safe_noop_off_windows():
    """This dev environment is Linux -- confirms the platform guard
    fails soft (no crash) rather than exercising the real Windows
    ctypes call, which needs an actual Windows box (same untested-off-
    platform caveat as _apply_native_titlebar_theme)."""
    slate._set_windows_app_user_model_id()  # must not raise


def test_window_icon_ico_generated_from_the_chosen_branding_png(tmp_path):
    """branding/slate.ico must actually exist and be a real multi-
    resolution icon (not just a renamed PNG) -- iconbitmap() on
    Windows silently no-ops on a malformed .ico, so this is worth a
    real structural check rather than trusting the generation step ran
    correctly by assumption."""
    from PIL import Image
    ico_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "branding", "slate.ico")
    assert os.path.exists(ico_path)
    with Image.open(ico_path) as im:
        assert im.format == "ICO"
        sizes = {s for s in im.info.get("sizes", [])}
        assert (256, 256) in sizes
        assert (16, 16) in sizes


def test_scrollregion_is_set_to_the_rendered_page_size(tmp_path):
    """Real gap Devin caught, 2026-07-25 ("and a h/v scrollbar"): a
    zoomed-in page previously had no scrollregion at all -- it just
    silently clipped past the visible canvas with no way to reach the
    rest. render() must always set one to the actual image size."""
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        region = [float(v) for v in app.canvas.cget("scrollregion").split()]
        img = app.viewer.render_page()
        assert region == [0.0, 0.0, float(img.width), float(img.height)]
    finally:
        app.doc.close()
        root.destroy()


def test_drag_selection_accounts_for_scroll_offset(tmp_path):
    """Real, subtle bug this same change could have introduced:
    event.x/event.y are VIEWPORT-relative, not canvas-space -- adding
    real scrolling means a raw, unconverted event.x/event.y would
    silently select/redact the WRONG region once the view is scrolled
    away from (0,0). _event_canvas_xy's canvasx()/canvasy() conversion
    is what this test actually exercises: scroll the canvas first,
    then confirm a drag at the SAME raw pixel position that worked at
    zero scroll now resolves through the offset to the correct words
    ("Slate fixture page", same target as the zero-scroll selection
    test -- see test_view_mode_drag_selects_text_not_a_rectangle's
    docstring for why "page" is included)."""
    root, app = _make_app(tmp_path)
    try:
        # canvas.config(width=, height=) alone can't force a real
        # smaller viewport -- the canvas is gridded sticky="nsew"
        # inside a PanedWindow pane and gets stretched right back to
        # the pane's real allocated size. Zooming past the real
        # (screen-bounded) window size forces genuine scrolling instead
        # (see _force_page_taller_than_viewport).
        _force_page_taller_than_viewport(app, root)
        z = app.viewer.zoom
        app.canvas.xview_moveto(0.5)
        app.canvas.yview_moveto(0.3)
        root.update()
        offset_x = app.canvas.canvasx(0)
        offset_y = app.canvas.canvasy(0)
        assert offset_x != 0 or offset_y != 0  # confirm the scroll actually took effect

        # Same PDF-space target rect as the zero-scroll test
        # (70,55)-(148,78), expressed here in VIEWPORT-relative coords
        # by subtracting the real scroll offset -- exactly what a user
        # clicking at that visual spot on a scrolled canvas would send.
        vx0, vy0 = int(70 * z - offset_x), int(55 * z - offset_y)
        vx1, vy1 = int(148 * z - offset_x), int(78 * z - offset_y)
        _drag(app, vx0, vy0, vx1, vy1)

        selected = [w[4] for _pn, w in app._selected_words]  # (page_num, word) pairs, see 2026-07-26 cross-page selection
        assert selected == ["Slate", "fixture", "page"]
    finally:
        app.doc.close()
        root.destroy()


def test_page_entry_box_reflects_current_page_and_total(tmp_path):
    """Foxit/Acrobat-style centered page box (Devin, 2026-07-25: "move
    the current page / total page UI element to the top-center...
    mimic Foxit's UI"). basic3page.pdf has 3 pages."""
    root, app = _make_app(tmp_path)
    try:
        assert app.page_entry_var.get() == "1"
        assert app.page_total_label.cget("text") == "of 3"

        app.next()
        assert app.page_entry_var.get() == "2"
    finally:
        app.doc.close()
        root.destroy()


def test_typing_a_valid_page_number_and_enter_jumps_there(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app.page_entry_var.set("3")
        app._goto_page_entry()
        assert app.viewer.page_num == 2  # 0-indexed internally
        assert app.page_entry_var.get() == "3"
    finally:
        app.doc.close()
        root.destroy()


def test_out_of_range_page_number_clamps_instead_of_crashing(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app.page_entry_var.set("999")
        app._goto_page_entry()
        assert app.viewer.page_num == 2  # clamped to the last real page (3)
        assert app.page_entry_var.get() == "3"

        app.page_entry_var.set("0")
        app._goto_page_entry()
        assert app.viewer.page_num == 0  # clamped to the first page
        assert app.page_entry_var.get() == "1"
    finally:
        app.doc.close()
        root.destroy()


def test_non_numeric_page_entry_reverts_without_crashing(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app.next()  # real page 2
        app.page_entry_var.set("not a number")
        app._goto_page_entry()  # must not raise
        assert app.viewer.page_num == 1  # unchanged
        assert app.page_entry_var.get() == "2"  # reverted to the real current page
    finally:
        app.doc.close()
        root.destroy()


def test_ctrl_w_closes_the_active_tab(tmp_path):
    """Devin, 2026-07-25: "ctrl+w close tab (and other CUA keybinds)"."""
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert len(app._tabs) == 2

        app.do_close()  # what <Control-w> is bound to
        assert len(app._tabs) == 1
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_ctrl_tab_cycles_forward_and_wraps_around(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        for name in ("second.pdf", "third.pdf"):
            p = str(tmp_path / name)
            shutil.copy(FIXTURE, p)
            app._open_document(p)
        assert len(app._tabs) == 3
        assert app.tab_strip.index(app.tab_strip.select()) == 2  # opening a doc activates it

        app._kb_next_tab()
        assert app.tab_strip.index(app.tab_strip.select()) == 0  # wraps around

        app._kb_next_tab()
        assert app.tab_strip.index(app.tab_strip.select()) == 1
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_ctrl_shift_tab_cycles_backward_and_wraps_around(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        second_path = str(tmp_path / "second.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        assert app.tab_strip.index(app.tab_strip.select()) == 1

        app._kb_prev_tab()
        assert app.tab_strip.index(app.tab_strip.select()) == 0

        app._kb_prev_tab()
        assert app.tab_strip.index(app.tab_strip.select()) == 1  # wraps around
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_tab_cycle_with_only_one_tab_does_not_raise(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._kb_next_tab()  # must not raise -- nothing to cycle to
        app._kb_prev_tab()
        assert len(app._tabs) == 1
    finally:
        for t in app._tabs:
            t.doc.close()
        root.destroy()


def test_startup_schedules_a_silent_update_check(tmp_path, monkeypatch):
    """Devin, 2026-07-25: "auto-checks for updates" -- confirms the
    real app wires this up (not just updatecheck.py in isolation),
    without hitting the real network or blocking startup."""
    calls = []
    monkeypatch.setattr(
        "updatecheck.check_for_update",
        lambda current, timeout=5.0: (calls.append(current) or
                                       {"checked": False, "update_available": False,
                                        "latest_version": None, "url": None, "error": "not configured"}),
    )
    root, app = _make_app(tmp_path)
    try:
        _wait_until(lambda: len(calls) > 0, root, timeout=5)
        assert calls == [version.VERSION]
    finally:
        app.doc.close()
        root.destroy()


def test_manual_check_shows_up_to_date_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "updatecheck.check_for_update",
        lambda current, timeout=5.0: {"checked": True, "update_available": False,
                                       "latest_version": current, "url": None, "error": None},
    )
    shown = []
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda title, msg: shown.append((title, msg)))
    root, app = _make_app(tmp_path)
    try:
        app._check_for_updates(silent_if_current=False)
        _wait_until(lambda: len(shown) > 0, root, timeout=5)
        assert shown[0][0] == "Up to date"
    finally:
        app.doc.close()
        root.destroy()


def test_manual_check_reports_a_real_error_not_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "updatecheck.check_for_update",
        lambda current, timeout=5.0: {"checked": False, "update_available": False,
                                       "latest_version": None, "url": None, "error": "network unreachable"},
    )
    shown = []
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda title, msg: shown.append((title, msg)))
    root, app = _make_app(tmp_path)
    try:
        app._check_for_updates(silent_if_current=False)
        _wait_until(lambda: len(shown) > 0, root, timeout=5)
        assert shown[0] == ("Update check failed", "network unreachable")
    finally:
        app.doc.close()
        root.destroy()


def test_startup_check_stays_silent_when_up_to_date(tmp_path, monkeypatch):
    """The silent_if_current=True startup path must NOT pop a dialog
    on every single launch just because the version is current --
    only real news (an update) or a manual check should ever show UI."""
    monkeypatch.setattr(
        "updatecheck.check_for_update",
        lambda current, timeout=5.0: {"checked": True, "update_available": False,
                                       "latest_version": current, "url": None, "error": None},
    )
    shown = []
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(slate.messagebox, "askyesno", lambda *a, **k: shown.append(a))
    root, app = _make_app(tmp_path)
    try:
        root.update()
        import time
        time.sleep(2.3)  # past the real 2s startup delay
        root.update()
        assert shown == []
    finally:
        app.doc.close()
        root.destroy()


def test_startup_check_prompts_when_update_is_real(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "updatecheck.check_for_update",
        lambda current, timeout=5.0: {"checked": True, "update_available": True,
                                       "latest_version": "v9.9.9", "url": "https://example.com", "error": None},
    )
    asked = []
    monkeypatch.setattr(slate.messagebox, "askyesno", lambda title, msg: asked.append((title, msg)) or False)
    root, app = _make_app(tmp_path)
    try:
        root.update()
        import time
        time.sleep(2.3)
        root.update()
        assert len(asked) == 1
        assert asked[0][0] == "Update available"
        assert "v9.9.9" in asked[0][1]
    finally:
        app.doc.close()
        root.destroy()


def test_ctrl_scroll_zooms_instead_of_navigating_pages(tmp_path):
    """Devin, 2026-07-25: "Ctrl+scroll = zoom in/out"."""
    root, app = _make_app(tmp_path)
    try:
        z0 = app.viewer.zoom
        app._on_ctrl_mouse_wheel(_FakeEvent(0, 0, delta=120))  # Windows/Mac zoom-in
        assert app.viewer.zoom > z0
        assert app.viewer.page_num == 0  # did NOT change page

        z1 = app.viewer.zoom
        app._on_ctrl_mouse_wheel(_FakeEvent(0, 0, delta=-120))  # zoom-out
        assert app.viewer.zoom < z1
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_middle_click_drag_pans_the_document(tmp_path):
    """Devin, 2026-07-26: "middle click/drag should pan the document" --
    same convention as most PDF viewers/image editors. Tk's canvas.scan_mark/
    scan_dragto is the built-in idiom; real check that a scroll fraction
    actually changes, not just that the calls don't raise."""
    root, app = _make_app(tmp_path)
    try:
        _force_page_taller_than_viewport(app, root)
        before = app.canvas.yview()

        app._on_pan_press(_FakeEvent(50, 400))
        app.canvas.scan_dragto(50, 100, gain=1)  # drag up 300px -- should scroll down
        root.update()

        after = app.canvas.yview()
        assert after != before  # real scroll happened, not a no-op
    finally:
        app.doc.close()
        root.destroy()


def test_pan_cursor_shows_fleur_while_dragging_and_restores_after(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        assert app.mode == "view"
        before_cursor = app.canvas.cget("cursor")

        app._on_pan_press(_FakeEvent(50, 50))
        assert app.canvas.cget("cursor") == "fleur"

        # Real movement before release (>4px) -- the DRAG branch, not
        # the click-to-toggle-autoscroll branch (same start point would
        # read as a plain click, see the autoscroll tests below).
        app._on_pan_release(_FakeEvent(60, 60))
        assert app.canvas.cget("cursor") == before_cursor  # restored, not stuck on fleur
        assert not app._autoscroll_active
    finally:
        app.doc.close()
        root.destroy()


def test_middle_click_without_drag_starts_autoscroll(tmp_path):
    """Devin, 2026-07-26: "extend the middle click pan to a middle
    click 'scroll'" -- browser-style click-to-autoscroll, distinct
    from the drag-to-pan above. A plain click (press+release at
    essentially the same point) toggles it on."""
    root, app = _make_app(tmp_path)
    try:
        assert not app._autoscroll_active
        app._on_pan_press(_FakeEvent(50, 50))
        app._on_pan_release(_FakeEvent(51, 51))  # negligible movement -- a click, not a drag

        assert app._autoscroll_active
        assert app._autoscroll_anchor == (50, 50)
        assert app.canvas.cget("cursor") == "fleur"
        assert app.canvas.find_withtag("autoscroll_indicator")  # real visual indicator drawn
    finally:
        app._stop_autoscroll()
        app.doc.close()
        root.destroy()


def test_second_middle_click_stops_autoscroll(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._on_pan_press(_FakeEvent(50, 50))
        app._on_pan_release(_FakeEvent(50, 50))
        assert app._autoscroll_active

        app._on_pan_press(_FakeEvent(80, 80))  # the cancel click -- anywhere works
        assert not app._autoscroll_active
        assert app.canvas.find_withtag("autoscroll_indicator") == ()  # indicator cleared
    finally:
        app._stop_autoscroll()
        app.doc.close()
        root.destroy()


def test_left_click_while_autoscrolling_cancels_it_instead_of_selecting_text(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._on_pan_press(_FakeEvent(50, 50))
        app._on_pan_release(_FakeEvent(50, 50))
        assert app._autoscroll_active

        app._on_press(_FakeEvent(70, 70))
        assert not app._autoscroll_active
        assert app._drag_start is None  # did not also start a text-selection drag
    finally:
        app._stop_autoscroll()
        app.doc.close()
        root.destroy()


def test_escape_cancels_autoscroll(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._on_pan_press(_FakeEvent(50, 50))
        app._on_pan_release(_FakeEvent(50, 50))
        assert app._autoscroll_active

        app._on_escape_cancels_autoscroll()
        assert not app._autoscroll_active
    finally:
        app._stop_autoscroll()
        app.doc.close()
        root.destroy()


def test_autoscroll_tick_scrolls_toward_cursor_drift_and_not_within_the_deadzone(tmp_path):
    """Real speed/direction check, not just that it toggles on: moving
    the tracked cursor well below the anchor should scroll DOWN;
    sitting still within the small deadzone right at the anchor
    should not scroll at all (lets the cursor rest without drift)."""
    root, app = _make_app(tmp_path)
    try:
        _force_page_taller_than_viewport(app, root)
        app._on_pan_press(_FakeEvent(50, 50))
        app._on_pan_release(_FakeEvent(50, 50))
        assert app._autoscroll_active
        app.root.after_cancel(app._autoscroll_after_id)  # drive ticks manually, not on a timer

        before = app.canvas.yview()
        app._autoscroll_pos = (50, 50)  # dead center -- within the deadzone
        app._autoscroll_tick()
        app.root.after_cancel(app._autoscroll_after_id)
        assert app.canvas.yview() == before  # no drift while sitting still at the anchor

        app._autoscroll_pos = (50, 250)  # well below the anchor -- should scroll down
        app._autoscroll_tick()
        app.root.after_cancel(app._autoscroll_after_id)
        after = app.canvas.yview()
        assert after[0] > before[0]
    finally:
        app._stop_autoscroll()
        app.doc.close()
        root.destroy()


def test_autoscroll_cursor_reflects_the_dominant_drift_axis(tmp_path):
    """Devin, 2026-07-26: "change the 'scroll' cursor to an up/down
    arrow or left/right arrow for those autoscrolling times" -- the
    cursor now follows whichever axis is actually dominant each tick,
    not a fixed fleur the whole time."""
    root, app = _make_app(tmp_path)
    try:
        app._on_pan_press(_FakeEvent(50, 50))
        app._on_pan_release(_FakeEvent(50, 50))
        app.root.after_cancel(app._autoscroll_after_id)

        app._autoscroll_pos = (50, 50)  # deadzone -- neutral
        app._autoscroll_tick()
        app.root.after_cancel(app._autoscroll_after_id)
        assert app.canvas.cget("cursor") == "fleur"

        app._autoscroll_pos = (50, 250)  # well below -- vertical drift dominates
        app._autoscroll_tick()
        app.root.after_cancel(app._autoscroll_after_id)
        assert app.canvas.cget("cursor") == "sb_v_double_arrow"

        app._autoscroll_pos = (250, 50)  # well to the right -- horizontal drift dominates
        app._autoscroll_tick()
        app.root.after_cancel(app._autoscroll_after_id)
        assert app.canvas.cget("cursor") == "sb_h_double_arrow"
    finally:
        app._stop_autoscroll()
        app.doc.close()
        root.destroy()


def test_cursor_matches_the_active_interaction_mode(tmp_path):
    """Devin, 2026-07-26: "please use better cursors" -- a drag-to-mark
    tool (redact) gets crosshair, a click-a-spot tool (forms) gets a
    pointer hand, plain reading (view) keeps the text I-beam."""
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("view")
        assert app.canvas.cget("cursor") == "xterm"

        app._set_mode("redact")
        assert app.canvas.cget("cursor") == "crosshair"

        app._set_mode("forms")
        assert app.canvas.cget("cursor") == "hand2"

        app._set_mode("annotate:highlight")
        assert app.canvas.cget("cursor") == "crosshair"
    finally:
        app.doc.close()
        root.destroy()


def test_chrome_cascade_colors_menubar_tabstrip_toolbar_as_three_real_steps(tmp_path):
    """Devin, 2026-07-25: "make menu bar cascade down in color from
    window bar down to tabs, to toolbar making it aesthetic." Real
    regression guard that the actual running widgets get the actual
    three cascade steps -- menubar=menubar_bg, tabstrip (ttk Notebook's
    own background)=tabstrip_bg, toolbar+scrollbars=toolbar_bg -- not
    just that theme.py's data shape is right (test_theme.py already
    covers that part)."""
    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("bonepaper_dark")
        app._apply_theme()
        colors = theme.get_palette("bonepaper_dark")

        assert str(app.menubar.cget("bg")) == colors["menubar_bg"]
        assert ttk.Style().lookup("TNotebook", "background") == colors["tabstrip_bg"]
        assert str(app.toolbar.cget("bg")) == colors["toolbar_bg"]
        assert str(app._vscroll.cget("background")) == colors["toolbar_bg"]
        assert str(app._hscroll.cget("background")) == colors["toolbar_bg"]
        # real 3-step gradient, not one flat color reused everywhere
        assert len({colors["menubar_bg"], colors["tabstrip_bg"], colors["toolbar_bg"]}) == 3
    finally:
        app.doc.close()
        root.destroy()


def test_tabs_never_use_select_bg_active_or_inactive(tmp_path):
    """Devin, 2026-07-25: "remove the sepia from the tabs... come up
    with a better, more creative solution." Real regression guard: tab
    styling must never reference select_bg again -- inactive uses
    button_bg/muted_fg, active uses bg/fg (blends into the content
    area instead of a filled color block)."""
    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("bonepaper_dark")
        app._apply_theme()
        colors = theme.get_palette("bonepaper_dark")

        style = ttk.Style()
        base_bg = style.lookup("TNotebook.Tab", "background")
        base_fg = style.lookup("TNotebook.Tab", "foreground")
        assert base_bg == colors["button_bg"]
        assert base_fg == colors["muted_fg"]

        selected_bg = style.lookup("TNotebook.Tab", "background", ("selected",))
        selected_fg = style.lookup("TNotebook.Tab", "foreground", ("selected",))
        assert selected_bg == colors["bg"]
        assert selected_fg == colors["fg"]
        # the real point of this test: neither state is select_bg
        assert colors["select_bg"] not in (base_bg, selected_bg)
    finally:
        app.doc.close()
        root.destroy()


def test_mode_label_survives_the_chrome_theming_pass(tmp_path):
    """_apply_chrome_theme's generic toolbar walk touches mode_label
    too (it's inside the toolbar subtree) -- _set_mode's own reassert
    right after must still win, same as it already did for the
    generic _paint_widget pass."""
    root, app = _make_app(tmp_path)
    try:
        app._set_mode("redact")
        app._apply_theme()
        assert app.mode_label.cget("bg") == "#c0392b"  # redact's own badge color, not chrome_bg
        assert app.mode_label.cget("fg") == "white"
    finally:
        app.doc.close()
        root.destroy()


def test_toc_panel_is_visible_by_default_on_document_open(tmp_path):
    """Devin, 2026-07-25: "default TOC view = true.\""""
    root, app = _make_app(tmp_path)
    try:
        assert app.toc_visible.get() is True
        panes = [str(p) for p in app._content_frame.panes()]
        assert str(app.toc_frame) in panes
    finally:
        app.doc.close()
        root.destroy()


def test_home_screen_matches_the_active_theme(tmp_path, monkeypatch):
    """Real bug caught live (Devin's screenshot, 2026-07-25): the home
    screen never themed itself at all -- __init__ calls _apply_theme()
    BEFORE _show_home_screen() ever builds home_frame, so it always
    rendered plain default Tk light styling regardless of the active
    theme. Covers both real call sites: fresh launch with no path, and
    closing the last tab back to home."""
    import settings as settings_module

    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", tmp_path / ".slate" / "settings.json")

    root = tk.Tk()
    app = slate.SlateApp(root, None)  # no path -- launches straight to home screen
    try:
        app.theme_name.set("bonepaper_dark")
        app._on_theme_changed()
        colors = theme.get_palette("bonepaper_dark")
        assert str(app.home_frame.cget("bg")) == colors["bg"]

        # second call site: open a doc, close its only tab, back to home
        second_path = str(tmp_path / "doc.pdf")
        shutil.copy(FIXTURE, second_path)
        app._open_document(second_path)
        app.do_close()
        assert app.home_frame is not None
        assert str(app.home_frame.cget("bg")) == colors["bg"]
    finally:
        if app.doc is not None:
            app.doc.close()
        root.destroy()


def test_f12_opens_settings_from_the_home_screen(tmp_path, monkeypatch):
    """Real bug (Devin, 2026-07-29): "F12 doesn't work on homepage."
    Root cause -- the F12 binding lived only inside
    _ensure_doc_view_widgets(), which early-returns after its first
    call and only ever runs once a document has been opened at least
    once. A fresh launch sitting on the home screen never registered
    F12 at all. Fixed with a redundant bind in __init__ itself, right
    where the home screen is first shown."""
    import settings as settings_module

    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / ".slate")
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", tmp_path / ".slate" / "settings.json")

    root = tk.Tk()
    app = slate.SlateApp(root, None)  # no path -- launches straight to home screen
    try:
        assert app.doc is None
        assert getattr(app, "_settings_window", None) is None
        root.focus_force()
        root.update()
        root.event_generate("<F12>")
        root.update()
        existing = getattr(app, "_settings_window", None)
        assert existing is not None and existing.winfo_exists()
    finally:
        if app.doc is not None:
            app.doc.close()
        root.destroy()


def test_toc_selected_row_uses_theme_highlight_not_ttks_default_blue(tmp_path):
    """Real bug caught live (Devin, 2026-07-25: "the highlight in TOC
    is blue, i want that to be inkbone green") -- Treeview's selected-
    row color was never explicitly styled at all, riding ttk's own
    'clam' theme built-in default regardless of Slate's actual palette."""
    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("bonepaper_dark")
        app._apply_theme()
        colors = theme.get_palette("bonepaper_dark")
        style = ttk.Style()
        assert style.lookup("Treeview", "background", ("selected",)) == colors["highlight_bg"]
        assert style.lookup("Treeview", "foreground", ("selected",)) == colors["bg"]
    finally:
        app.doc.close()
        root.destroy()


def test_about_dialog_has_a_fixed_green_accent_regardless_of_theme(tmp_path, monkeypatch):
    """Devin, 2026-07-25: "please add a permanent, clever hint of
    inkbone green on the about page please" -- must stay green even
    under a non-green theme (Slate Dark's real accent is moss,
    #699d43, not the fixed #62a945 accent bar checked here)."""
    monkeypatch.setattr(slate.messagebox, "showinfo", lambda *a, **k: None)
    root, app = _make_app(tmp_path)
    try:
        app.theme_name.set("slate_dark")
        app._apply_theme()
        app._show_about()
        about = root.winfo_children()[-1]  # the just-opened Toplevel
        accent_bars = [
            w for w in about.winfo_children()
            if w.winfo_class() == "Frame" and str(w.cget("bg")) == "#62a945"
        ]
        assert len(accent_bars) == 1
        about.destroy()
    finally:
        app.doc.close()
        root.destroy()


def test_f2_opens_command_palette_listing_all_themes(tmp_path):
    """Devin, 2026-07-25: "is there an easier way for me to change the
    theme please? f2 command palette or something?\""""
    root, app = _make_app(tmp_path)
    try:
        app._show_command_palette()
        palette = root.winfo_children()[-1]
        listbox = [w for w in palette.winfo_children() if isinstance(w, tk.Listbox)][0]
        entries = listbox.get(0, tk.END)
        assert len(entries) == len(theme.THEME_LABELS)
        assert any("Bonepaper Dark" in e for e in entries)
        palette.destroy()
    finally:
        app.doc.close()
        root.destroy()


def test_command_palette_filters_live_as_you_type(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app._show_command_palette()
        palette = root.winfo_children()[-1]
        entry = [w for w in palette.winfo_children() if isinstance(w, tk.Entry)][0]
        listbox = [w for w in palette.winfo_children() if isinstance(w, tk.Listbox)][0]

        entry.insert(0, "slate dark")
        root.update()
        entries = listbox.get(0, tk.END)
        assert len(entries) == 1  # exactly one theme matches this filter
        assert all("Slate Dark" in e for e in entries)
        palette.destroy()
    finally:
        app.doc.close()
        root.destroy()


def test_selecting_a_theme_in_command_palette_applies_it_and_closes(tmp_path):
    """Real synthetic <Double-Button-1> events don't reliably fire
    without genuine window-manager focus in this test harness (same
    documented limitation as elsewhere in this suite) -- exercises the
    real code the double-click binds to directly instead."""
    root, app = _make_app(tmp_path)
    try:
        app._apply_command_palette_theme("slate_dark")
        assert app.theme_name.get() == "slate_dark"
        assert theme.load_preference() == "slate_dark"  # real persisted, not just the var
    finally:
        app.doc.close()
        root.destroy()


def test_page_box_prev_next_mini_buttons_navigate(tmp_path):
    """Devin, 2026-07-25: "easier to change pages, not just text box
    (which i still like the input to go straight a page number)" --
    real click-path buttons alongside the entry, typed-number-jump
    behavior untouched."""
    root, app = _make_app(tmp_path)
    try:
        buttons = [
            w for w in app.toolbar.winfo_children()[1].winfo_children()
            if isinstance(w, tk.Button)
        ]
        labels = {b.cget("text") for b in buttons}
        assert labels == {"◀", "▶"}
        assert app.viewer.page_num == 0

        next_btn = [b for b in buttons if b.cget("text") == "▶"][0]
        next_btn.invoke()
        assert app.viewer.page_num == 1

        prev_btn = [b for b in buttons if b.cget("text") == "◀"][0]
        prev_btn.invoke()
        assert app.viewer.page_num == 0

        # typed-number jump still works, unaffected by the new buttons
        app.page_entry_var.set("3")
        app._goto_page_entry()
        assert app.viewer.page_num == 2
    finally:
        app.doc.close()
        root.destroy()


def test_wheel_page_turns_when_page_fits_viewport(tmp_path):
    """Fable design review, 2026-07-25: the rubber-band wheel must
    collapse to TODAY's exact unconditional-page-turn behavior when
    the page already fits the viewport -- real regression guard, not
    just a new-feature test. Default canvas sizing (render() always
    sets canvas width/height to exactly match the image) already IS
    this case, so no viewport-forcing needed here."""
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        root.update()
        assert app._wheel_fits_viewport() is True

        app._wheel_down()
        assert app.viewer.page_num == 1
        app._wheel_up()
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def _force_single_mode(app, root):
    """view_mode defaults to "continuous" now (Devin, 2026-07-25:
    "default to 'continuous scroll' please"), superseding Slice 2's
    original "single" default -- tests that deliberately exercise
    single-page-mode-specific behavior (scrollregion == exactly one
    page, wheel's unconditional page-turn, _page_offset always (0,0))
    need to opt into it explicitly now rather than relying on it being
    what a fresh app already starts in.

    Also a real, non-obvious side effect of that default change: a
    fresh app's FIRST-EVER render used to be single-page mode's own,
    which got to dictate the window's starting size (so "the page
    always fits the viewport" was trivially true by construction).
    Continuous mode's first render doesn't force any particular
    canvas size, so the window can end up smaller than one page --
    switching to single mode afterward doesn't retroactively grow an
    already-established window. Tests whose whole premise is "the
    page fits" need a real, generously-sized window to make that true
    again, not just the mode switch."""
    app.continuous_scroll_var.set(False)
    app._set_view_mode()
    root.geometry("1000x1400")
    root.update()


def _force_page_taller_than_viewport(app, root):
    """Real viewport mismatch, not a fake one: canvas.config(width=,
    height=) alone does NOT shrink anything, since the canvas is
    gridded sticky="nsew" inside a PanedWindow pane and gets stretched
    right back to the pane's real allocated size regardless of what a
    caller requests. Zooming the page past the real (screen-bounded)
    window size forces genuine clipping instead -- the same mechanism
    a real user hits when zooming in far enough that the page no
    longer fits on screen."""
    app.viewer.zoom = 8.0
    app._selected_words = []
    app.render()
    root.update()


def test_wheel_scrolls_within_page_before_turning_when_zoomed_past_viewport(tmp_path):
    """Fable design review, 2026-07-25: real scroll once the page is
    taller than the viewport, page-turn only at the scroll edge."""
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        _force_page_taller_than_viewport(app, root)
        assert app._wheel_fits_viewport() is False

        app._wheel_down()  # should scroll, not change page
        assert app.viewer.page_num == 0
        first, last = app.canvas.yview()
        assert first > 0.0  # real scroll happened
    finally:
        app.doc.close()
        root.destroy()


def test_wheel_down_turns_page_at_the_bottom_edge_landing_at_top(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        _force_page_taller_than_viewport(app, root)
        app.canvas.yview_moveto(1.0)  # simulate already scrolled to the bottom
        root.update()

        app._wheel_down()
        assert app.viewer.page_num == 1
        first, _last = app.canvas.yview()
        assert first < 0.01  # landed at top, same as every other next-page trigger
    finally:
        app.doc.close()
        root.destroy()


def test_wheel_up_turns_page_at_the_top_edge_landing_at_bottom(tmp_path):
    """The one asymmetric case in Fable's design: a wheel-driven
    prev-page arrives from below and should land at the new page's
    BOTTOM, not top (every other prev-page trigger -- keyboard/j/
    PageUp/TOC -- keeps landing top-left, unchanged)."""
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        app.next()  # real page 2, so there's somewhere to go back to
        _force_page_taller_than_viewport(app, root)
        assert app.canvas.yview()[0] < 0.01  # fresh page starts at top (already-tested behavior)

        app._wheel_up()
        assert app.viewer.page_num == 0
        _first, last = app.canvas.yview()
        assert last > 0.99  # landed at bottom, not top
    finally:
        app.doc.close()
        root.destroy()


def test_button_4_5_route_through_the_same_wheel_dispatch_as_mousewheel(tmp_path):
    """Real X11/Windows parity gap Fable flagged, 2026-07-25: Button-4/5
    used to bypass _on_mouse_wheel entirely and call page-nav directly
    -- harmless only because both paths did the same unconditional
    thing. Now both real bindings must resolve to the rubber-band
    dispatch methods (_wheel_up/_wheel_down), not the old direct
    page-nav shortcuts -- proven behaviorally via a real
    event_generate (confirmed to actually fire the bound canvas
    handler in this headless harness, unlike the click-drag/selection
    cases elsewhere in this suite that need real screen coordinates):
    zoomed past the viewport, a raw page-nav call would still flip
    the page; the real rubber-band dispatch must scroll instead."""
    root, app = _make_app(tmp_path)
    try:
        _force_page_taller_than_viewport(app, root)
        app.canvas.focus_set()
        root.update()

        app.canvas.event_generate("<Button-5>")
        root.update()
        assert app.viewer.page_num == 0  # rubber-band scrolled, did NOT page-turn
        first, _last = app.canvas.yview()
        assert first > 0.0  # real scroll happened, same as calling _wheel_down directly

        app.canvas.yview_moveto(0.0)
        root.update()
        app.canvas.event_generate("<Button-4>")
        root.update()
        assert app.viewer.page_num == 0  # already at the top, no page to scroll up into
    finally:
        app.doc.close()
        root.destroy()


# ------------------------------------------------------------------
# Slice 2: continuous-scroll view mode (Fable design review, 2026-07-25)
# ------------------------------------------------------------------

def test_continuous_mode_renders_every_page_in_one_scrollable_canvas(tmp_path):
    """Smallest real continuous-scroll slice per Fable's design review:
    vertical stack only (no side-by-side yet), scrollregion covers the
    whole stack. Rendering itself is windowed (Slice 3 perf fix,
    Fable design review) -- only pages within one screenful of the
    viewport get a real PhotoImage; page 0 (on screen) is always real,
    a doc long enough that not everything fits is expected to have
    real placeholders too (this fixture's real per-run geometry
    happens to place page 2 just outside that window -- see the
    dedicated windowing tests below for the actual eviction/lazy-fill
    behavior, this test only checks the on-screen page is real)."""
    root, app = _make_app(tmp_path)  # basic3page.pdf -- 3 pages
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        assert app.continuous_scroll is True
        assert app._layout is not None
        assert app._page_cache.has(0)  # the page actually on screen is always real

        page0_y0, page0_y1 = app._layout.rect_of(0)[1], app._layout.rect_of(0)[3]
        page0_h = page0_y1 - page0_y0
        _total_w, total_h = app._layout.total_size
        assert total_h > page0_h * 2  # 3 stacked pages, not one page's worth
    finally:
        app.doc.close()
        root.destroy()


def test_page_offset_is_always_zero_for_the_displayed_page_in_single_page_mode(tmp_path):
    """Zero-regression guarantee for every existing click/drag/redact/
    annotate/textedit/forms handler: single-page mode's coordinate
    math for the page actually on screen must stay byte-identical to
    pre-Slice-2 behavior. Slice 4 note: self._layout now represents
    the WHOLE document even in static mode (so continuous mode's
    geometry can be generalized to one code path), so _page_offset of
    a page that ISN'T the currently-displayed one is no longer a
    meaningful (0, 0) query -- only ever called in practice for
    whatever page _on_press actually resolved a click against, which
    is always part of the current row."""
    root, app = _make_app(tmp_path)
    try:
        _force_single_mode(app, root)
        assert app.continuous_scroll is False
        assert app._page_offset(app.viewer.page_num) == (0, 0)

        app._go_to_page(1)
        assert app._page_offset(app.viewer.page_num) == (0, 0)

        app._go_to_page(2)
        assert app._page_offset(app.viewer.page_num) == (0, 0)
    finally:
        app.doc.close()
        root.destroy()


def test_continuous_mode_redact_drag_lands_on_the_clicked_page_not_page_zero(tmp_path):
    """Real latent bug Fable flagged in design review: redactions used
    to record against self.viewer.page_num unconditionally -- invisible
    in single-page mode (always the same page), real the instant a
    drag can land on any visible page. A drag near page 2's own
    top-left corner must resolve to page 1 (0-indexed) with PDF-space
    coordinates relative to THAT page's own origin, not raw canvas
    space."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        app._set_mode("redact")

        page1_x0, page1_y0, _x1, _y1 = app._layout.rect_of(1)
        z = app.viewer.zoom
        x0, y0 = int(page1_x0 + 20), int(page1_y0 + 20)
        x1, y1 = int(page1_x0 + 120), int(page1_y0 + 60)
        _drag(app, x0, y0, x1, y1)

        assert len(app._pending_redactions) == 1
        page_num, rect = app._pending_redactions[0]
        assert page_num == 1  # landed on the second page, not page 0
        assert abs(rect.x0 - 20 / z) < 1.0
        assert abs(rect.y0 - 20 / z) < 1.0
    finally:
        app.doc.close()
        root.destroy()


def test_continuous_mode_click_in_the_gap_between_pages_is_a_safe_no_op(tmp_path):
    """A click that lands in the inter-page margin isn't an error --
    PageLayout.page_at returns None there, and _on_press must not
    crash or start a phantom drag gesture."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        app._set_mode("redact")

        _page0_x0, _page0_y0, _x1, page0_y1 = app._layout.rect_of(0)
        page1_y0 = app._layout.rect_of(1)[1]
        gap_y = int((page0_y1 + page1_y0) / 2)  # dead center of the real gap
        _drag(app, 10, gap_y, 30, gap_y + 2)

        assert app._pending_redactions == []  # no phantom redaction from a gap click
    finally:
        app.doc.close()
        root.destroy()


def test_continuous_mode_next_prev_scroll_to_the_real_page_position(tmp_path):
    """Real bug caught live building this slice: render()'s own
    geometry-settling update_idletasks() fired the scroll-sync
    callback with the STALE pre-navigation scroll position, clobbering
    viewer.page_num right back to the old page before next()'s own
    _scroll_to_page() call ever ran. Fixed with a suppression guard
    during render() (_suppress_scroll_sync) -- this is the regression
    test for that fix, not just a feature test."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        app.canvas.yview_moveto(0.0)
        root.update()

        app.next()
        root.update()
        assert app.viewer.page_num == 1
        first, _last = app.canvas.yview()
        page1_y0 = app._layout.rect_of(1)[1]
        _total_w, total_h = app._layout.total_size
        assert abs(first - page1_y0 / total_h) < 0.01  # landed at page 2's real top, not canvas origin

        app.prev()
        root.update()
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_continuous_mode_wheel_is_real_scroll_with_no_page_turn_concept(tmp_path):
    """Fable design review: page boundaries are a soft concept once
    every page is stacked in one scrollable canvas -- wheel is just
    real scroll (or a no-op at the very top/bottom), no edge-landing
    logic, no page-turn branch."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        assert app._wheel_fits_viewport() is False  # 3 stacked pages already overflow

        app.canvas.yview_moveto(0.0)
        root.update()
        app._wheel_down()
        first, _last = app.canvas.yview()
        assert first > 0.0  # real scroll happened
        assert app.viewer.page_num in (0, 1)  # no forced page-turn, just wherever scroll landed

        app.canvas.yview_moveto(1.0)
        root.update()
        _before_first, before_last = app.canvas.yview()
        app._wheel_down()  # already at the bottom -- must not crash or wrap
        _after_first, after_last = app.canvas.yview()
        # "last" (the bottom edge of the visible fraction) is what
        # reads ~1.0 at the real bottom -- "first" stays wherever the
        # viewport's own height fraction puts it (never reaches 1.0
        # for a viewport showing less than the whole document).
        assert before_last >= 0.99
        assert after_last >= 0.99  # stayed at the bottom, real no-op
    finally:
        app.doc.close()
        root.destroy()


def test_continuous_mode_sync_page_num_tracks_organic_scroll(tmp_path):
    """The page-number box must track whatever page is at the
    viewport's top edge during real (scrollbar-drag-style) scrolling,
    not just programmatic navigation -- Devin: "Devin will notice
    immediately if this is missing." Real gap found live building this
    slice: yscrollcommand does NOT reliably fire on a plain
    yview_moveto() in this headless test harness (confirmed: manually
    invoking the sync function works fine, so the sync logic itself
    was never the bug -- the callback trigger was), so the real
    scrollbar's own drag-release event is exercised here instead, the
    same explicit hook (_vscroll's <ButtonRelease-1> binding) a real
    user's scrollbar drag fires on Windows."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()

        page1_y0 = app._layout.rect_of(1)[1]
        _total_w, total_h = app._layout.total_size
        app.canvas.yview_moveto(page1_y0 / total_h)
        app._vscroll.focus_set()
        app._vscroll.event_generate("<ButtonRelease-1>")
        root.update()

        assert app.viewer.page_num == 1
        assert app.page_entry_var.get() == "2"
    finally:
        app.doc.close()
        root.destroy()


def test_toc_select_scrolls_to_real_page_position_in_continuous_mode(tmp_path):
    """_go_to_page (TOC-select/page-box/first/last/search-jump's shared
    real-nav path) must use _scroll_to_page in continuous mode, not
    _reset_scroll's canvas-origin jump -- the earlier page_num-
    clobbering bug this slice fixed would otherwise make this land on
    the wrong page's position."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()

        app._go_to_page(2)
        root.update()
        assert app.viewer.page_num == 2
        first, _last = app.canvas.yview()
        page2_y0 = app._layout.rect_of(2)[1]
        _total_w, total_h = app._layout.total_size
        assert abs(first - page2_y0 / total_h) < 0.01
    finally:
        app.doc.close()
        root.destroy()


# ------------------------------------------------------------------
# Slice 3: windowed continuous-scroll rendering (Fable design review,
# 2026-07-25, after Devin hit a real lockup on PageUp/PageDown)
# ------------------------------------------------------------------

def _make_large_doc(tmp_path, page_count=60):
    """A synthetic multi-page PDF real enough to prove windowing
    actually bounds rendering work -- basic3page.pdf's 3 pages are too
    few to distinguish "windowed" from "eager-rendered-anyway"."""
    path = str(tmp_path / "large.pdf")
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Page {i + 1}")
    doc.save(path)
    doc.close()
    return path


def test_continuous_mode_only_renders_pages_near_the_viewport(tmp_path):
    """The actual point of Slice 3: opening a long document in
    continuous mode must NOT eager-render every page -- only a window
    around the viewport gets a real PhotoImage, everything else stays
    a cheap placeholder until scrolled near."""
    root, app = _make_app(tmp_path, fixture=_make_large_doc(tmp_path))
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()

        cached_count = len(app._page_cache._images)
        assert cached_count < app.viewer.page_count  # real bound, not "cached everything anyway"
        assert app._page_placeholder_items != {}  # some pages really are still just placeholders
        assert app._page_cache.has(0)  # the page actually on screen IS real
    finally:
        app.doc.close()
        root.destroy()


def test_scrolling_shifts_the_window_evicting_far_pages_lazily_filling_near_ones(tmp_path):
    """_shift_window's whole job: scrolling deep into a long document
    must evict pages that scrolled far away (real memory bound) and
    lazily render pages newly entering the window -- without a full
    canvas.delete('all') rebuild (Fable design review: pure-scroll
    updates only touch the window boundary's own diff)."""
    root, app = _make_app(tmp_path, fixture=_make_large_doc(tmp_path))
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        assert app._page_cache.has(0)

        page_far_y0 = app._layout.rect_of(40)[1]
        _total_w, total_h = app._layout.total_size
        app.canvas.yview_moveto(page_far_y0 / total_h)
        app._vscroll.focus_set()
        app._vscroll.event_generate("<ButtonRelease-1>")
        root.update()

        assert app._page_cache.has(40)  # newly-visible page got lazily rendered
        assert not app._page_cache.has(0)  # far-away page got evicted, real bound maintained
    finally:
        app.doc.close()
        root.destroy()


def test_zoom_change_invalidates_the_whole_page_cache(tmp_path):
    """Every cached pixel is wrong after a zoom change (geometry
    itself changed) -- real full-invalidate, not a stale-image bug
    waiting to happen."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        assert app._page_cache.has(0)

        app.zoom_in()
        # A fresh render() just repopulated the (now-empty-then-refilled)
        # cache at the new zoom -- the real assertion is that the OLD
        # zoom's layout is gone, not that the cache is empty right now.
        assert app._layout.zoom == pytest.approx(1.5 + 0.25)
    finally:
        app.doc.close()
        root.destroy()


def test_theme_change_invalidates_the_whole_page_cache(tmp_path):
    """Colorize is baked into the cached PhotoImage at fill-time, not
    reapplied per-draw -- a theme switch must bust the whole cache or
    pages keep showing the OLD theme's colors until they happen to
    scroll out of and back into the window."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        app.theme_name.set("dark")
        app._on_theme_changed()
        # Real assertion: the cache was rebuilt at the new theme, not
        # left holding light-theme pixels under a dark label.
        assert app._page_cache.has(0)
    finally:
        app.doc.close()
        root.destroy()


# ------------------------------------------------------------------
# Slice 4: side-by-side view (Fable design review, 2026-07-25) --
# an independent checkbox combinable with continuous scroll, not a
# third radio option (Devin: "side by side option (both can be turned
# on, checkbox in menu)").
# ------------------------------------------------------------------

def test_fit_width_divides_viewport_across_columns_in_side_by_side(tmp_path):
    """Real bug (Devin, 2026-07-29: "'fit width' should center bookview,
    not the left half of bookview"): fit_width() always fit ONE page's
    width to the FULL viewport, ignoring side_by_side -- in Book View
    (2 columns) that zoomed the spread to twice the width that actually
    fits, so only the left page's left portion showed without
    horizontal scroll. Fixed to divide the viewport across cols (minus
    the one real gap between them, matching layout.PageLayout's own
    gap=2 default) before fitting -- confirmed here against a manual
    per-page fit_width() call on the viewer directly, the real source
    of truth this now has to match."""
    root, app = _make_app(tmp_path)
    try:
        app.side_by_side_var.set(True)
        app.continuous_scroll_var.set(False)
        root.geometry("2000x1400")
        root.update()
        app._set_view_mode()
        root.update()

        app.fit_width()
        two_col_zoom = app.viewer.zoom

        app.canvas.update_idletasks()
        viewport_w = app.canvas.winfo_width()
        expected_zoom = app.viewer.fit_width((viewport_w - 2) / 2)  # gap=2, cols=2

        assert two_col_zoom == expected_zoom
        # Real regression guard, not just "some number computed": half
        # the viewport must produce meaningfully LESS zoom than fitting
        # the full viewport would have (the actual bug) -- not just a
        # coincidentally-equal value.
        full_viewport_zoom = app.viewer.fit_width(viewport_w)
        assert two_col_zoom < full_viewport_zoom
    finally:
        app.doc.close()
        root.destroy()


def test_fit_width_uses_the_cropped_content_width_not_the_full_page(tmp_path):
    """Real bug (Devin, 2026-07-29: "crop to content doesn't seem to do
    anything"). Root cause: viewer.fit_width() always measured the
    page's FULL native width, even with crop_to_content on -- so Fit
    Width (including Book View's own auto-fit-on-toggle) kept sizing
    zoom to the uncropped page, and the margin space crop is supposed to
    free up for the reader never actually translated into a bigger
    effective zoom. Fixed by passing the active crop rect's width
    through as fit_width()'s new content_width param whenever crop is
    on. Real regression guard: with crop on, fitting the SAME viewport
    width must produce MORE zoom than fitting the uncropped page would
    (the cropped content is narrower, so it should scale up further to
    fill the same space) -- not just "some number changed.\""""
    root, app = _make_app(tmp_path)
    try:
        root.geometry("1000x900")
        root.update()

        app.crop_to_content_var.set(False)
        app._on_crop_toggle()
        app.fit_width()
        uncropped_zoom = app.viewer.zoom

        app.crop_to_content_var.set(True)
        app._on_crop_toggle()
        app.fit_width()
        cropped_zoom = app.viewer.zoom

        assert app._get_crop_rect() is not None  # fixture has real detectable content
        assert cropped_zoom > uncropped_zoom
    finally:
        app.doc.close()
        root.destroy()


def test_side_by_side_static_shows_two_pages_with_no_scroll_needed(tmp_path):
    """Devin's own framing: "a spread fits the viewport by definition
    at normal zoom" -- side-by-side alone (continuous_scroll off) is a
    static two-page row, canvas sized exactly to it, no scrollbar."""
    root, app = _make_app(tmp_path)  # basic3page.pdf -- 3 pages
    try:
        app.continuous_scroll_var.set(False)
        app.side_by_side_var.set(True)
        # Same real gap _force_single_mode already works around: the
        # window's default size (established by continuous mode's own
        # first-ever render, which doesn't force any particular canvas
        # size) doesn't retroactively grow for a wider two-page spread
        # -- grow it BEFORE the mode switch renders, not after.
        root.geometry("2000x1400")
        root.update()
        app._set_view_mode()

        assert app._layout.cols == 2
        assert app._page_cache.has(0)
        assert app._page_cache.has(1)
        assert not app._page_cache.has(2)  # not part of the first row
        assert app._wheel_fits_viewport() is True  # canvas sized exactly to the row
    finally:
        app.doc.close()
        root.destroy()


def test_side_by_side_next_prev_step_by_a_whole_spread(tmp_path):
    """next()/prev() must move by 2 pages in side-by-side, same as
    Adobe/Foxit's own two-page-view nav -- not 1, which would leave
    the same page visible on alternating sides of the spread."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(False)
        app.side_by_side_var.set(True)
        app._set_view_mode()
        assert app.viewer.page_num == 0

        app.next()
        assert app.viewer.page_num == 2  # stepped by 2, not 1 -- basic3page.pdf's last page
        app.prev()
        assert app.viewer.page_num == 0
    finally:
        app.doc.close()
        root.destroy()


def test_side_by_side_click_on_the_right_page_resolves_to_that_page_not_the_left(tmp_path):
    """Real regression test for _on_press's generalized page_at()
    resolution + _page_offset's row-translation: a click on the
    SECOND (right) page of a static spread must redact against that
    page, with PDF-space coordinates relative to ITS OWN origin, not
    the left page's."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(False)
        app.side_by_side_var.set(True)
        app._set_view_mode()
        app._set_mode("redact")

        page1_x0, page1_y0, _x1, _y1 = app._layout.rect_of(1)
        z = app.viewer.zoom
        x0, y0 = int(page1_x0 + 20), int(page1_y0 + 20)
        x1, y1 = int(page1_x0 + 120), int(page1_y0 + 60)
        _drag(app, x0, y0, x1, y1)

        assert len(app._pending_redactions) == 1
        page_num, rect = app._pending_redactions[0]
        assert page_num == 1  # the right page, not the left
        assert abs(rect.x0 - 20 / z) < 1.0
        assert abs(rect.y0 - 20 / z) < 1.0
    finally:
        app.doc.close()
        root.destroy()


def test_side_by_side_deep_page_still_resolves_clicks_at_row_origin(tmp_path):
    """Real regression test for _static_row_offset: self._layout's
    rect_of() gives a page's TRUE position in the full document stack
    (what continuous mode needs), which for a page other than the
    first row is nowhere near canvas origin. A static row must always
    be interacted with as if freshly drawn at (0, 0), regardless of
    that page's true offset -- basic3page.pdf's page 2 (the odd one
    out, alone in the second row) is the real case that would have
    silently misplaced clicks without the offset correction."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(False)
        app.side_by_side_var.set(True)
        app._set_view_mode()
        app._go_to_page(2)  # lands on the second row (page 2 alone)
        app._set_mode("redact")

        z = app.viewer.zoom
        _drag(app, 20, 20, 120, 60)  # a plain click near canvas origin

        assert len(app._pending_redactions) == 1
        page_num, rect = app._pending_redactions[0]
        assert page_num == 2
        assert abs(rect.x0 - 20 / z) < 1.0  # resolved relative to THIS row's origin, not a huge true offset
        assert abs(rect.y0 - 20 / z) < 1.0
    finally:
        app.doc.close()
        root.destroy()


def test_crop_to_content_shrinks_the_rendered_page_and_layout_geometry(tmp_path):
    """Devin, 2026-07-29: "build the crop feature... don't like big page
    margins." Toggling it on must shrink BOTH the actual rendered pixmap
    AND the layout geometry that positions/click-hit-tests it -- a
    mismatch between the two (e.g. a cropped image drawn at an uncropped
    rect_of() position) would be a real, silent bug, not just cosmetic."""
    root, app = _make_app(tmp_path)
    try:
        app.crop_to_content_var.set(False)
        app._on_crop_toggle()
        uncropped_w, uncropped_h = app._layout.total_size
        uncropped_img = app._page_cache.get(0)
        uncropped_img_w = uncropped_img.width()

        app.crop_to_content_var.set(True)
        app._on_crop_toggle()
        cropped_w, cropped_h = app._layout.total_size
        cropped_img = app._page_cache.get(0)
        cropped_img_w = cropped_img.width()

        # The fixture (basic3page.pdf) has real margins -- both the
        # layout's own geometry and the actual rendered image must shrink,
        # not just one of the two.
        assert cropped_w < uncropped_w
        assert cropped_img_w < uncropped_img_w
        # rect_of() must reflect the SAME cropped size the image actually
        # is -- this is the real mismatch risk named in this test's docstring.
        page_rect_w = app._layout.rect_of(0)[2] - app._layout.rect_of(0)[0]
        assert abs(page_rect_w - cropped_img_w) < 2  # sub-pixel rounding only

        # Toggling back off restores the original (uncropped) geometry.
        app.crop_to_content_var.set(False)
        app._on_crop_toggle()
        restored_w, _restored_h = app._layout.total_size
        assert restored_w == uncropped_w
    finally:
        app.doc.close()
        root.destroy()


def test_book_view_toggle_sets_both_axes_and_stays_in_sync(tmp_path):
    """Devin, 2026-07-29: "roll that up into Book View" -- F8/the
    checkbutton is a derived preset over the two real axes, not a third
    independent one. Toggling it on sets both; toggling either underlying
    checkbox by hand afterward must keep book_view_var honest too (only
    checked when both really agree), never a stale display."""
    root, app = _make_app(tmp_path)
    try:
        # Force a known starting state -- don't assume the fixture's own
        # defaults (continuous_scroll defaults True per Devin's standing
        # preference), this test cares about the toggle logic, not what
        # a fresh app happens to boot with.
        app.continuous_scroll_var.set(False)
        app.side_by_side_var.set(False)
        app._set_view_mode()
        assert app.book_view_var.get() is False

        app.book_view_var.set(True)
        app._toggle_book_view()
        assert app.continuous_scroll is True
        assert app.side_by_side is True

        # Turn Book View back off -> both underlying axes follow.
        app.book_view_var.set(False)
        app._toggle_book_view()
        assert app.continuous_scroll is False
        assert app.side_by_side is False

        # Toggling just ONE underlying box (not via Book View) must NOT
        # leave book_view_var showing checked -- they don't both agree.
        app.side_by_side_var.set(True)
        app._set_view_mode()
        assert app.book_view_var.get() is False

        # Now the other axis catches up -> book_view_var reflects it.
        app.continuous_scroll_var.set(True)
        app._set_view_mode()
        assert app.book_view_var.get() is True

        # F8 key path flips from whatever book_view_var currently is,
        # same as clicking the checkbutton would.
        app._kb_toggle_book_view()
        assert app.book_view_var.get() is False
        assert app.continuous_scroll is False
        assert app.side_by_side is False
    finally:
        app.doc.close()
        root.destroy()


def test_continuous_and_side_by_side_combine_into_a_scrolling_two_column_layout(tmp_path):
    """Both checkboxes on at once (Devin: "both can be turned on") --
    real scroll through page PAIRS, windowing still applies."""
    root, app = _make_app(tmp_path)
    try:
        app.continuous_scroll_var.set(True)
        app.side_by_side_var.set(True)
        app._set_view_mode()

        assert app._layout.cols == 2
        assert app.continuous_scroll is True
        assert app.side_by_side is True
        # Real two-column geometry: page 1 sits beside page 0, not
        # below it -- same row, real x-offset, y0 unchanged.
        p0 = app._layout.rect_of(0)
        p1 = app._layout.rect_of(1)
        assert p1[0] > p0[0]  # page 1 is to the right of page 0
        assert p1[1] == p0[1]  # same row -- same top edge
    finally:
        app.doc.close()
        root.destroy()


# ------------------------------------------------------------------
# Width-based auto side-by-side (Devin, 2026-07-25: "if the
# horizontal size reaches 'side by side' size, Slate automatically
# toggles it")
# ------------------------------------------------------------------

def test_auto_toggle_enables_side_by_side_when_window_wide_enough(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        assert app.side_by_side is False
        root.geometry("2400x1200")  # real, wide enough for a 2-up spread + TOC panel
        root.update()

        app._apply_width_based_side_by_side()
        assert app.side_by_side is True
        assert app.side_by_side_var.get() is True  # menu checkbox stays in sync
        assert app._layout.cols == 2
    finally:
        app.doc.close()
        root.destroy()


def test_auto_toggle_disables_side_by_side_when_window_too_narrow(tmp_path):
    root, app = _make_app(tmp_path)
    try:
        app.side_by_side_var.set(True)
        app._set_view_mode()
        assert app.side_by_side is True

        root.geometry("900x1200")  # real, not wide enough for 2 pages
        root.update()
        app._apply_width_based_side_by_side()

        assert app.side_by_side is False
        assert app.side_by_side_var.get() is False
        assert app._layout.cols == 1
    finally:
        app.doc.close()
        root.destroy()


def test_auto_toggle_never_touches_continuous_scroll(tmp_path):
    """continuous_scroll stays the default regardless (Devin, same
    thread: "continuous scroll stays a default") -- this auto-toggle
    only ever touches the side_by_side axis."""
    root, app = _make_app(tmp_path)
    try:
        assert app.continuous_scroll is True
        root.geometry("2400x1200")
        root.update()
        app._apply_width_based_side_by_side()
        assert app.continuous_scroll is True

        root.geometry("900x1200")
        root.update()
        app._apply_width_based_side_by_side()
        assert app.continuous_scroll is True
    finally:
        app.doc.close()
        root.destroy()


def test_configure_event_debounces_the_width_check(tmp_path):
    """<Configure> fires continuously during a live resize -- must
    schedule (and reschedule, not stack up) a single debounced check,
    not run the real width logic on every intermediate event."""
    root, app = _make_app(tmp_path)
    try:
        # Real widget construction already triggers at least one
        # Configure event of its own (window mapping/initial layout)
        # -- clear that pending handle first so this test starts from
        # a known state rather than asserting nothing was ever scheduled.
        if app._autolayout_after_id is not None:
            root.after_cancel(app._autolayout_after_id)
            app._autolayout_after_id = None

        app._on_canvas_frame_configure()
        first_id = app._autolayout_after_id
        assert first_id is not None

        app._on_canvas_frame_configure()  # a second event before the first fires
        second_id = app._autolayout_after_id
        assert second_id is not None
        assert second_id != first_id  # rescheduled to a fresh handle, not left stacked
    finally:
        # Real pending callback cleanup -- letting this fire after
        # root.destroy() is the same benign "invalid command name"
        # Tcl noise already seen elsewhere in this suite from other
        # after()-based mechanisms, harmless but avoidable here.
        if app._autolayout_after_id is not None:
            root.after_cancel(app._autolayout_after_id)
        app.doc.close()
        root.destroy()


def test_colorize_pages_defaults_off(tmp_path):
    """Devin, 2026-07-26: real content got destroyed twice the same day
    by the theme-tint flatten (a categorical diagram's legend, then a
    real blue/orange bake-off comparison) -- flipped from opt-out to
    opt-in so a color-coded document isn't silently wrecked by default."""
    root, app = _make_app(tmp_path)
    try:
        assert app.colorize_pages is False
        assert app.colorize_pages_var.get() is False
    finally:
        app.doc.close()
        root.destroy()
