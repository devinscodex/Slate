#!/usr/bin/env python3
"""Slate — entry point and UI integration. Wires viewer, redact,
annotate, merge_split, forms, sign, security, scan, recent, io_pdf
together into one menu-driven app. Business logic lives in the
per-feature modules; this file is glue + Tkinter widgets only.
"""
import colorsys
import math
import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageTk

import annotate
import convert
import epubfix
import forms
import gate
import io_pdf
import layout
import merge_split
import pagecache
import recent
import redact
import scan
import search
import security
import settings
import sign
import singleinstance
import tab as tabmodule
import textedit
import theme
import tts
import updatecheck
import version
from viewer import Viewer, detect_content_bbox
from playback import Player as TTSPlayer

_TAB_CLOSE_GLYPH = "×"  # visual hint only -- middle-click actually closes, see _on_tab_strip_click

# Tk's radiobutton/checkbutton checked-indicator (selectcolor) defaults
# to a mid-gray that can vanish against a dark theme's background.
# Bright green reads against light OR dark backgrounds, so one fixed
# value here (not re-themed live) is more robust than tracking every
# radio/checkbutton through every theme switch.
RADIO_SELECT_COLOR = "#4a9e3a"


def _wcag_contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Real WCAG 2.x relative-luminance contrast ratio (the same formula
    behind the 3:1/4.5:1 accessibility thresholds), not a cheap RGB-
    distance approximation -- used by _wire_toggle_button_contrast to
    pick a measured checked-state text color per theme rather than a
    guessed one."""
    def _luminance(hexval):
        hexval = hexval.lstrip("#")
        def chan(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hexval[i:i + 2], 16) for i in (0, 2, 4))
        r, g, b = chan(r), chan(g), chan(b)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    la, lb = _luminance(hex_a), _luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)

# These are Tk's own built-in NAMED fonts -- virtually every stock
# Tk/ttk widget (Label, Button, Menu, Entry, Listbox, Notebook tabs,
# Treeview) defaults to one of these unless a widget explicitly
# overrides its own font, so reconfiguring just these few font objects
# (not walking every widget by hand) scales the whole UI via one shared
# Tk mechanism. TkFixedFont included (code-view/monospace text).
# Deliberately excludes TkCaptionFont/TkSmallCaptionFont/TkIconFont/
# TkTooltipFont -- Slate never uses window-manager captions or system
# tooltips, so touching those would be dead code.
_UI_SCALABLE_FONTS = (
    "TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont",
)

# Extensions fitz/PyMuPDF would otherwise refuse outright ("Failed to
# open file '...' as type ps1") because it only infers document type
# from the extension and doesn't recognize these as text, even though
# the content is byte-identical to a .txt file it opens fine. Passing
# filetype="txt" explicitly for these makes them open as plain
# monospace text (no syntax coloring -- not built).
CODE_TEXT_EXTENSIONS = (
    ".ps1", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml",
    ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".css", ".sql", ".ini", ".cfg",
)

# Menu labels that only make sense for a real PDF (mutation/signing/
# forms/etc) -- disabled whenever the active tab's document isn't one.
# PyMuPDF/MuPDF also opens EPUB/MOBI/FB2/CBZ/TXT/MD natively --
# view/search/TOC/keyboard nav all already work unchanged on those,
# only these PDF-specific actions need gating.
_FILE_PDF_ONLY_LABELS = [
    "Save", "Save As...", "Merge PDFs...", "Split into pages...",
    "Encrypt...", "Sign (self-signed test cert)...",
]
_EDIT_PDF_ONLY_LABELS = [
    "Redact (drag a region)", "Apply pending redactions + Save As...",
    "Highlight (drag)", "Rectangle (drag)", "Freetext note (click)",
    "Stamp: Approved (click)", "Fill form field (click)",
    "Edit Text (locked, click)...",
]


class SlateApp:
    def __init__(self, root, path=None):
        self.root = root
        # Loaded once here, before anything below reads THEMES/
        # THEME_LABELS (including the very next line) -- not at module
        # import time, so `import theme` stays side-effect-free for
        # tests. Restores any user-saved custom themes (save_as_new_theme)
        # and per-theme chrome-key overrides (the Edit Colors dialog's
        # "derived" fields, when hand-edited) into the live roster.
        theme.load_custom_themes()
        theme.load_saved_chrome_overrides()
        # Set before any other widget exists (even before root.title())
        # so the very first paint already uses the right color, not a
        # visible flash from light to a saved dark preference a moment
        # later.
        root.configure(bg=theme.get_palette(theme.load_preference())["bg"])
        # Persisted user prefs: loaded once here, applied below as each
        # corresponding variable's initial value. self._saved_zoom is
        # kept separately (not applied yet) since no Viewer/document
        # exists this early -- _open_document applies it once a doc is
        # loaded.
        _saved = settings.load()
        self._saved_zoom = _saved["zoom"]
        self._saved_open_tabs = _saved["open_tabs"]
        # Capture each named font's real platform-native size ONCE,
        # before touching anything -- Tk's own DPI/OS-aware default, not
        # a guessed constant, so the same integer delta reads as a
        # proportionally similar bump regardless of native size.
        # Applied before _build_menu() or any widget exists, so the
        # first paint already uses the saved size.
        self.ui_font_scale = _saved["ui_font_scale"]
        self._ui_font_base_sizes = {}
        for _name in _UI_SCALABLE_FONTS:
            try:
                self._ui_font_base_sizes[_name] = tkfont.nametofont(_name).cget("size")
            except tk.TclError:
                continue  # a platform build missing one of these named fonts -- skip, don't crash
        self._apply_ui_font_scale()
        self.path = None
        self.doc = None
        self.viewer = None
        self.page = None
        # _colorize_for_theme flattens every page to the theme's fg/bg
        # pair so documents visually match the app chrome -- correct
        # default for prose/book reading, but it destroys real color
        # content (a categorical-color-coded diagram, a photo) where
        # color IS the information. Per-session toggle.
        self.colorize_pages = _saved["colorize_pages"]
        self.check_updates_on_start = _saved["check_updates_on_start"]
        # One shared crop rect (viewer.detect_content_bbox) applied to
        # every page, cached per DOCUMENT (self._crop_rect, keyed by
        # self._crop_rect_doc) since sampling several pages' real
        # text/image/drawing bboxes isn't free and the result doesn't
        # change unless the document itself changes. Default off --
        # opt-in, not sprung on an existing workflow.
        self.crop_to_content = _saved.get("crop_to_content", False)
        self._crop_rect = None
        self._crop_rect_doc = None
        self._tk_img = None  # keep a reference or Tkinter garbage-collects it
        self.mode = "view"  # view | redact | annotate:<kind> | forms | textedit
        self._drag_start = None
        self._drag_rect_id = None
        self._corner_grip_start = None  # (start mouse x/y, start window w/h) for the bottom-right resize grip
        self._pending_redactions = []  # [(page_num, fitz.Rect), ...]
        # Each entry is a fitz word tuple (x0, y0, x1, y1, word,
        # block_no, line_no, word_no) -- page.get_text("words") already
        # returns words in natural reading order, so the selected subset
        # stays correctly ordered without re-sorting by geometry.
        self._selected_words = []  # (page_num, word) pairs, can span multiple pages
        self._selection_highlight_photos = []  # PhotoImage refs for the current selection overlay -- see _draw_text_selection_for_page
        self._search_highlight_photos = []  # PhotoImage refs for the current search-match overlay -- see _draw_search_highlights_for_page
        # Two INDEPENDENT axes, not one mode string -- matches how
        # Adobe/Foxit's own "Two Page View" + "Scroll Continuously"
        # checkboxes combine. continuous_scroll is the "does the canvas
        # scroll through every row" axis; side_by_side is the "how many
        # pages per row" axis (cols=2 vs 1). self._layout
        # (layout.PageLayout) exists in ALL FOUR combinations -- every
        # coordinate-resolution call site generalizes to "does
        # self._layout exist" rather than a mode check.
        self.continuous_scroll = _saved["continuous_scroll"]
        self.side_by_side = _saved["side_by_side"]
        # side_by_side stays a plain bool (2 columns vs 1, what the View
        # menu's "Side by Side" checkbox + settings.json persistence
        # still mean) for backward compat; num_columns is the real
        # render-time column count, auto-recomputed from the
        # live viewport width by _apply_width_based_side_by_side below
        # (every old "2 if self.side_by_side else 1" call site now
        # reads this instead). Seeded from the persisted bool so the
        # very first render (before any width measurement has happened)
        # still gets a sane 1-or-2 starting value.
        self.num_columns = 2 if self.side_by_side else 1
        # A manually-picked count PINS num_columns -- the width-based
        # auto-follow (_apply_width_based_side_by_side) checks this
        # first and does nothing while pinned, so it can't silently
        # overwrite a manual choice on the next resize. Session-scoped
        # only: every fresh launch starts unpinned (real auto).
        self._columns_pinned = False
        self._layout = None
        # Static (non-scrolling) row rendering draws the CURRENT row
        # translated to canvas origin (0, 0) -- self._layout's own
        # rect_of() gives each page's TRUE position in the full
        # document stack (needed for continuous mode), which for a
        # page deep in a long document is nowhere near the canvas
        # origin. This is the correction applied both when drawing a
        # static row and when resolving a click back to PDF space
        # (_page_offset) -- always (0, 0) in continuous mode, where
        # rect_of()'s true absolute position is exactly what's wanted.
        self._static_row_offset = (0, 0)
        self._autolayout_after_id = None  # debounce handle for _on_canvas_frame_configure
        # render()'s own geometry-settling update_idletasks() calls
        # (scrollregion/width/height config) fire the canvas's
        # yscrollcommand with whatever scroll position was current
        # BEFORE this render -- without suppression, navigating to page
        # 2 in continuous mode would synchronously clobber
        # viewer.page_num right back to the OLD page via that stale
        # callback, before _go_to_page's own _scroll_to_page() call ever
        # ran. Suppressed during render() itself; real organic scrolling
        # (wheel/scrollbar-drag) is unaffected.
        self._suppress_scroll_sync = False
        self._drag_page = None  # page a click/drag started on, pinned for the whole gesture (continuous mode: a drag can visually cross page rects, but a redaction/annotation belongs to exactly one page)
        self._drag_anchor_pdf = None  # (x, y) in PDF space where the drag started -- text-flow selection's fixed start point, see _on_press/_on_drag
        self._pan_press_pos = None  # canvas (x, y) at ButtonPress-2 -- distinguishes a real drag-pan from a plain click (autoscroll toggle) at release
        self._autoscroll_active = False
        self._autoscroll_anchor = None  # (x, y), fixed for the session -- speed/direction come from cursor drift away from this point
        self._autoscroll_pos = None  # live cursor (x, y), updated by _on_canvas_motion
        self._autoscroll_indicator_id = None
        self._autoscroll_after_id = None
        # Continuous mode renders windowed, not every page on every
        # render() call: self._page_cache holds PhotoImages only for
        # pages near the viewport (it IS the keepalive; no separate list
        # needed), self._layout_doc/_last_window/_page_canvas_items/
        # _page_placeholder_items track what's currently drawn so
        # scrolling can incrementally shift the window instead of
        # rebuilding from scratch (see _render_continuous/_shift_window).
        self._page_cache = pagecache.PageImageCache(self._make_page_image)
        self._layout_doc = None
        self._last_window = set()
        self._page_canvas_items = {}
        self._page_placeholder_items = {}
        self._doc_view_built = False
        self.home_frame = None
        self.toc_visible = tk.BooleanVar(value=_saved["toc_visible"])
        self.check_updates_on_start_var = tk.BooleanVar(value=self.check_updates_on_start)
        self.theme_name = tk.StringVar(value=theme.load_preference())
        # Read Aloud (TTS): app-wide, not per-tab -- reading one document
        # while switching tabs isn't a supported combination in v1.
        self.tts_voice = tk.StringVar(value=_saved["tts_voice"])
        self.tts_speed = tk.DoubleVar(value=_saved["tts_speed"])  # user-facing multiplier, not Piper's length_scale directly
        self.tts_player = TTSPlayer()
        # Which page do_read_page() actually started reading, kept fixed
        # even if the user scrolls/navigates elsewhere while listening.
        # See _update_tts_highlight for the estimation method.
        self._tts_reading_page = None
        self._tts_reading_page_num = None
        # The EXACT word list actually synthesized -- needed since a
        # "read from here" click trims the START of what's read, so
        # _update_tts_highlight can't just re-derive the full page's
        # words from scratch. See _update_tts_highlight's own docstring.
        self._tts_reading_words = []
        self._tts_chunk_sample_counts = []  # real per-sentence audio durations from tts.synthesize(), see _update_tts_highlight
        # True between do_read_document() and either reaching the end of
        # the document or an explicit Stop -- _poll_tts_playback_state
        # uses _tts_was_playing to tell a real natural end-of-audio
        # apart from an explicit pause.
        self._tts_reading_document = False
        self._tts_was_playing = False
        # Gated feature (DESIGN.md's "Text editing"): a local UX gate,
        # not real access control -- re-locks every restart on purpose.
        self._textedit_unlocked_this_session = False
        self.search_state = search.SearchState()
        # Tabs: self._tabs / self._tab_frames are parallel, index-aligned
        # lists (one real Tab per open document, one placeholder Notebook
        # child frame -- never itself shown, just there so the Notebook
        # widget has something to select). self._active_tab is whichever
        # Tab's fields are currently loaded into the flat attributes above.
        self._tabs = []
        self._tab_frames = []
        self._active_tab = None

        root.title("Slate")
        self._set_window_icon()
        self._build_menu()
        self._apply_theme()  # establishes the ttk 'clam' baseline even in light mode

        if path:
            # Explicit command-line/IPC-handoff path always wins over
            # session restore -- opening a specific file is a deliberate
            # ask, not something a leftover saved tab list should compete
            # with.
            self._open_document(path)
        elif self._saved_open_tabs:
            # Missing/moved files are skipped silently rather than
            # erroring on launch over a file that's since been deleted.
            # Each entry is normally {"path": ..., "page": N}, but an
            # older settings.json may still have plain path strings --
            # handled here rather than forcing a migration.
            for entry in self._saved_open_tabs:
                saved_path = entry["path"] if isinstance(entry, dict) else entry
                saved_page = entry.get("page") if isinstance(entry, dict) else None
                if os.path.exists(saved_path):
                    self._open_document(saved_path)
                    if saved_page is not None and self.viewer is not None:
                        saved_page = max(0, min(saved_page, self.viewer.page_count - 1))
                        self._go_to_page(saved_page)
            if not self._tabs:
                self._show_home_screen()
        else:
            self._show_home_screen()

        # F12 (Settings) bound here too, redundant with the copy inside
        # _ensure_doc_view_widgets() -- that method only runs once the
        # first document opens, so a fresh launch sitting on the home
        # screen would never register F12 otherwise. _show_settings()
        # already tolerates no open document (its own zoom-label line
        # checks self.viewer).
        self.root.bind("<F12>", lambda e: self._show_settings())

        # Delayed 2s so it never competes with initial doc-load/render
        # for the same event loop; silent unless there's real news (see
        # _check_for_updates's docstring). Settings > "Check for updates
        # on start" opts out of even this silent background check.
        if self.check_updates_on_start:
            self.root.after(2000, lambda: self._check_for_updates(silent_if_current=True))

    # ------------------------------------------------------------------
    # menu
    # ------------------------------------------------------------------
    def _set_window_icon(self):
        """Purely cosmetic -- must never crash the app if the branding
        asset is missing (e.g. a stripped-down deployment without
        branding/). Keeps a reference on self (same PhotoImage-gets-
        garbage-collected gotcha as self._tk_img in render()).

        iconphoto() alone (the original implementation) sets the
        in-app titlebar icon reasonably well cross-platform, but real
        Windows TASKBAR icons are a separate, Windows-specific
        mechanism -- iconbitmap(default=...) with a real multi-
        resolution .ico (branding/slate.ico, generated from
        icon_b_redaction_bar.png via Pillow's ICO writer) is what
        Windows actually reads for the taskbar/Alt-Tab icon. NOT
        live-verified against a real Windows box (same caveat as
        _apply_native_titlebar_theme).
        """
        branding_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "branding")
        try:
            self._icon_img = tk.PhotoImage(file=os.path.join(branding_dir, "icon_b_redaction_bar.png"))
            self.root.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass
        if platform.system() == "Windows":
            ico_path = os.path.join(branding_dir, "slate.ico")
            try:
                self.root.iconbitmap(default=ico_path)
            except tk.TclError:
                pass

    def _on_theme_changed(self):
        theme.save_preference(self.theme_name.get())
        self._apply_theme()
        if self.doc is not None:
            # Colorize happens once at cache-fill time (baked into the
            # stored PhotoImage), not reapplied per-draw -- a theme
            # switch is a full cache bust, same cost as a zoom change.
            self._page_cache.invalidate_all()
            self.render()  # re-invert the currently-visible page immediately, not on next nav

    def _apply_ui_font_scale(self):
        """Reconfigures Tk's own shared named fonts (_UI_SCALABLE_FONTS)
        by self.ui_font_scale points -- every stock widget referencing
        one of them (almost everything: menus, buttons, labels, tabs,
        the TOC treeview, dialogs) picks up the new size immediately,
        with no per-widget font-walking needed. Preserves each font's
        own SIGN: Tk font sizes are negative when the platform expressed
        them in pixels rather than points (common on Windows) -- adding
        a positive delta to a negative number would shrink it, the
        opposite of what a '+' click should do, so this scales the
        magnitude and re-applies the original sign. Floored at 6 (points
        or pixels) so an aggressive negative scale can never shrink text
        to nothing."""
        for name, base_size in self._ui_font_base_sizes.items():
            sign = -1 if base_size < 0 else 1
            magnitude = max(6, abs(base_size) + self.ui_font_scale)
            tkfont.nametofont(name).configure(size=sign * magnitude)

    def _wire_toggle_button_contrast(self, widget, variable, value=None, fixed_theme_name=None):
        """indicatoron=False Checkbutton/Radiobutton widgets (Settings
        dialog's Theme/Mode/Display/Voice/Speed toggles) fill their ENTIRE
        background with selectcolor when checked. selectcolor is each
        theme's own select_bg (the same accent reserved for "selection
        roles only" everywhere else), not one fixed universal color --
        but that accent ranges from very dark to very light across
        themes, so a single static text color can't stay readable in
        both the checked and unchecked state.

        Checked-state text picks WHICHEVER of colors["bg"]/colors["fg"]
        has the higher real WCAG contrast ratio against
        colors["select_bg"] (see _wcag_contrast_ratio), not a blind
        "always bg" assumption -- bg wins for most themes, but fg wins
        for themes where bg sits too close in luminance to their own
        accent (below the 3:1 UI-text floor using bg). Unchecked state
        stays the plain colors["fg"] on colors["bg"] either way.

        value (for a Radiobutton sharing ONE variable across several
        buttons, e.g. the Theme grid's self.theme_name or Voice/Speed's
        shared vars): "checked" means variable.get() == value, not the
        variable's own truthiness. None (the default) covers a plain
        per-widget Checkbutton/BooleanVar instead, where the variable's
        own value already IS the checked state.

        fixed_theme_name (Theme grid only): each radio there represents
        a SPECIFIC theme, not "whichever theme happens to be active" --
        "Bonepaper Dark"'s own swatch must show Bonepaper's own accent
        even while Slate is the live theme, so this pins which palette
        _refresh reads colors from instead of always reading
        self.theme_name.get(). None (every other group) means "whatever
        the active theme's own accent is," which is what a plain feature
        toggle actually wants.

        Looks up the theme fresh on every call (not a colors snapshot
        from wire-time) so this stays correct across a later theme
        switch too -- a trace on the variable covers a checked-state
        change; _paint_widget calls the stored callback directly on
        every repaint to cover a theme change with no checked-state
        change."""
        def _is_checked():
            return variable.get() == value if value is not None else bool(variable.get())
        def _refresh(*_a):
            cur_colors = theme.get_palette(fixed_theme_name or self.theme_name.get())
            # selectcolor was only ever set ONCE at construction time,
            # under whatever theme was active when this singleton dialog
            # was first built -- switching themes later (in the same
            # still-open dialog session) repainted bg/fg everywhere via
            # _paint_widget, but selectcolor itself (a separate Tk
            # widget option _paint_widget never touches) stayed frozen
            # on the OLD theme's accent. Mode/Display/Voice/Speed must
            # track whichever theme is CURRENTLY active (fixed_theme_name
            # is None for all of them); only the Theme grid's own
            # per-swatch buttons (fixed_theme_name set) are deliberately
            # exempt -- their selectcolor stays pinned to that swatch's
            # own theme forever, never the active one.
            if fixed_theme_name is None:
                widget.configure(selectcolor=cur_colors["select_bg"])
            if _is_checked():
                bg_contrast = _wcag_contrast_ratio(cur_colors["bg"], cur_colors["select_bg"])
                fg_contrast = _wcag_contrast_ratio(cur_colors["fg"], cur_colors["select_bg"])
                checked_fg = cur_colors["bg"] if bg_contrast >= fg_contrast else cur_colors["fg"]
                widget.configure(fg=checked_fg)
            else:
                widget.configure(fg=cur_colors["fg"])
        variable.trace_add("write", _refresh)
        widget.slate_toggle_button = True
        widget.slate_fixed_theme_name = fixed_theme_name
        widget._slate_refresh_toggle_fg = _refresh
        _refresh()

    def _ui_header_font(self, extra=0, weight="bold"):
        """A header/title font sized relative to the CURRENT (possibly
        user-scaled) TkDefaultFont, not a hardcoded absolute point size
        -- so About/Settings/home-screen headers scale along with the
        rest of the UI instead of staying fixed while everything else
        around them grows or shrinks (the real gap a flat
        `font=("TkDefaultFont", 14, "bold")` tuple had)."""
        base = abs(tkfont.nametofont("TkDefaultFont").cget("size"))
        return ("TkDefaultFont", base + extra, weight)

    def _on_ui_font_scale_change(self, delta):
        base_default = abs(self._ui_font_base_sizes.get("TkDefaultFont", 10))
        # Symmetric floor/ceiling around 0: never shrink the base font
        # below 6pt/px, never grow past +20 -- generous either direction
        # without letting a runaway click sequence produce something
        # absurd or degenerate.
        self.ui_font_scale = max(6 - base_default, min(20, self.ui_font_scale + delta))
        settings.save({"ui_font_scale": self.ui_font_scale})
        self._apply_ui_font_scale()

    def _on_colorize_toggle(self):
        # Same cache-bust discipline as _on_theme_changed -- colorize is
        # baked into the cached PhotoImage at fill-time, not reapplied
        # per-draw, so a toggle needs a full invalidate to take effect
        # immediately instead of on next nav.
        self.colorize_pages = self.colorize_pages_var.get()
        settings.save({"colorize_pages": self.colorize_pages})
        if self.doc is not None:
            self._page_cache.invalidate_all()
            self.render()

    def _on_crop_toggle(self):
        # Same cache-bust discipline as _on_colorize_toggle -- crop is
        # baked into the cached PhotoImage's actual pixel size at
        # fill-time (get_pixmap(clip=...)), not reapplied per-draw.
        # Also drops self._layout (not just the page cache): the crop
        # rect changes every rect_of() coordinate too, not just pixel
        # content, so a stale layout would draw newly-cropped images at
        # OLD (uncropped) positions.
        self.crop_to_content = self.crop_to_content_var.get()
        settings.save({"crop_to_content": self.crop_to_content})
        if self.doc is not None:
            self._page_cache.invalidate_all()
            self._layout = None
            self.render()

    def _on_check_updates_toggle(self):
        self.check_updates_on_start = self.check_updates_on_start_var.get()
        settings.save({"check_updates_on_start": self.check_updates_on_start})

    def _apply_native_titlebar_theme(self, window=None):
        """The window title bar itself is drawn by the OS, not Tk --
        genuinely an "outer" component no amount of widget.configure()
        can touch. Windows 10 (2004+)/11 support a real, documented DWM
        attribute for this (DWMWA_USE_IMMERSIVE_DARK_MODE = 20).
        Best-effort only: wrapped broadly because ctypes.windll doesn't
        exist at all off Windows, and older Windows builds don't
        support this attribute -- failing soft just means the title bar
        stays whatever it already was, never a crash. NOT live-verified
        against a real Windows box (this dev environment is Linux).

        window: content colors (Tk's job) and the native OS titlebar (a
        completely separate mechanism) can repaint independently --
        defaults to self.root; _show_settings/_show_about also pass
        their own Toplevel here, both at open time and on every live
        theme switch while still open."""
        if platform.system() != "Windows":
            return
        target = window if window is not None else self.root
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(target.winfo_id())
            is_dark = theme.get_palette(self.theme_name.get())["is_dark"]
            value = ctypes.c_int(1 if is_dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            pass

    def _apply_theme(self):
        """Recursively repaints every widget currently in the tree, so
        it works uniformly whether called at startup, on a live toggle,
        or after opening a fresh dialog -- one mechanism instead of
        theming persistent widgets (toolbar/canvas/tabs) and freshly-
        built ones (home screen) two different ways.

        Platform constraint (see theme.py's own docstring): tk.Menu
        dropdown popups are drawn by the native Win32 renderer on
        Windows and ignore these colors there -- harmless to set
        anyway, and correct on Linux/X11.
        """
        colors = theme.get_palette(self.theme_name.get())
        self.root.configure(bg=colors["bg"])
        self._paint_widget(self.root, colors)
        self._apply_native_titlebar_theme()

        style = ttk.Style()
        style.theme_use("clam")
        # tabstrip_bg, not plain bg -- the Notebook's own background is
        # the MIDDLE step of the menubar->tabstrip->toolbar cascade.
        style.configure("TNotebook", background=colors["tabstrip_bg"], borderwidth=0)
        # Inactive tabs: button_bg/muted_fg (a quiet card). Active tabs:
        # active_tab_bg (theme.py's own chrome-cascade addition, 35%
        # toward select_bg from button_bg) -- a subtle tint, not a full
        # fill, using each family's own accent hue.
        style.configure(
            "TNotebook.Tab", background=colors["button_bg"], foreground=colors["muted_fg"]
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", colors["active_tab_bg"])],
            foreground=[("selected", colors["fg"])],
        )
        style.configure(
            "Treeview",
            background=colors["entry_bg"],
            foreground=colors["fg"],
            fieldbackground=colors["entry_bg"],
        )
        # Selected-row color, genuinely theme-driven via highlight_bg
        # (not ttk's own 'clam' theme built-in blue-ish default).
        style.map(
            "Treeview",
            background=[("selected", colors["highlight_bg"])],
            foreground=[("selected", colors["bg"])],
        )

        self._apply_chrome_theme(colors)

        if hasattr(self, "mode_label"):
            self._set_mode(self.mode)  # reassert redact's red badge over the generic pass

    def _apply_chrome_theme(self, colors):
        """The chrome cascade, same rule for every family -- see
        theme.py's _with_chrome_cascade for the 3-step values
        (menubar_bg = bg, tabstrip_bg = midpoint, toolbar_bg =
        button_bg). This method applies menubar_bg/fg to the menubar
        and toolbar_bg/fg to the toolbar + scrollbars, overriding the
        generic bg/fg the recursive _paint_widget pass already applied
        to them as plain Frames/Labels/Buttons. tabstrip_bg is applied
        separately, via ttk.Style's "TNotebook" background above (a
        ttk widget, not part of this plain-Tk walk). Menu itself is
        native-rendered on Windows -- setting it anyway is harmless and
        correct on Linux.
        """
        if hasattr(self, "menubar"):
            try:
                self.menubar.configure(bg=colors["menubar_bg"], fg=colors["menubar_fg"])
            except tk.TclError:
                pass
        if hasattr(self, "toolbar"):
            self._paint_chrome_subtree(self.toolbar, colors["toolbar_bg"], colors["toolbar_fg"])
            # Real per-family border (theme.py's authored `border` key,
            # not computed) -- for most families a subtle neutral step,
            # for bonepaper dark specifically the accent-tinted "glow"
            # webUI's own --line uses there. highlightthickness=1 draws
            # on all 4 edges, reading as a real bordered panel rather
            # than a bare color-block, same as webUI's own bordered
            # toolbar/inputrow chrome.
            self.toolbar.configure(highlightthickness=1, highlightbackground=colors["border"], highlightcolor=colors["border"])
        for scrollbar in (getattr(self, "_vscroll", None), getattr(self, "_hscroll", None)):
            if scrollbar is not None:
                try:
                    scrollbar.configure(
                        background=colors["toolbar_bg"], troughcolor=colors["bg"],
                        activebackground=colors["highlight_bg"],
                    )
                except tk.TclError:
                    pass
        if getattr(self, "_corner_grip", None) is not None:
            self._draw_corner_grip(colors)

    def _draw_corner_grip(self, colors):
        """The bottom-right corner where the h/v scrollbars collide.
        Dagaz (ᛞ) from TART's own rune palette -- its shape (two
        triangles meeting at a point) reads naturally as a resize
        handle. Rendered in the same neutral chrome text color as the
        rest of the toolbar band, not a special accent."""
        g = self._corner_grip
        g.configure(bg=colors["toolbar_bg"])
        g.delete("all")
        g.create_text(11, 11, text="ᛞ", font=("TkDefaultFont", 14),
                       fill=colors["toolbar_fg"], anchor="center")

    def _on_corner_grip_press(self, event):
        """Standard OS bottom-right window-resize convention, hand-rolled
        because the hitbox needs to be bigger than a bare ttk.Sizegrip's
        default (~17px vs this widget's 22px) and this corner already
        has to be a real widget anyway (the rune icon lives here).
        Position captured here too (not just size) -- see
        _on_corner_grip_drag for why."""
        self._corner_grip_start = (
            event.x_root, event.y_root,
            self.root.winfo_width(), self.root.winfo_height(),
            self.root.winfo_x(), self.root.winfo_y(),
        )

    def _on_corner_grip_drag(self, event):
        """A size-only geometry string ("WxH", no "+x+y") can get
        re-anchored by the window manager instead of preserving the
        existing top-left corner, on the first resize call after the
        window's position was last set with its own separate
        geometry("+x+y") call -- Tk has no guarantee the WM keeps
        remembering a position it wasn't just told. Fix: always pass
        position explicitly, pinned to what it was when the drag
        started."""
        if self._corner_grip_start is None:
            return
        start_x, start_y, start_w, start_h, win_x, win_y = self._corner_grip_start
        dx, dy = event.x_root - start_x, event.y_root - start_y
        new_w = max(400, start_w + dx)
        new_h = max(300, start_h + dy)
        self.root.geometry(f"{new_w}x{new_h}+{win_x}+{win_y}")

    def _paint_chrome_subtree(self, widget, band_bg, band_fg):
        try:
            cls = widget.winfo_class()
            if cls in ("Frame",):
                widget.configure(bg=band_bg)
            elif cls in ("Label", "Button"):
                widget.configure(bg=band_bg, fg=band_fg)
        except tk.TclError:
            pass  # mode_label's red badge (redact mode) and similar owned-elsewhere widgets skip cleanly
        for child in widget.winfo_children():
            self._paint_chrome_subtree(child, band_bg, band_fg)

    def _paint_widget(self, widget, colors):
        if widget is getattr(self, "mode_label", None):
            pass  # _set_mode owns this widget's colors, reasserted after the walk
        elif getattr(widget, "slate_muted", False):
            widget.configure(bg=colors["bg"], fg=colors["muted_fg"])
        elif getattr(widget, "slate_fixed_bg", None):
            # A widget meant to stay ONE fixed color regardless of theme
            # (e.g. About's permanent green accent bar) -- one flag, one
            # config call, no re-assertion needed at every call site.
            widget.configure(bg=widget.slate_fixed_bg)
        elif getattr(widget, "slate_accent_swatch", False):
            # Opposite of slate_fixed_bg above -- this one is SUPPOSED
            # to change with the active theme, so it reads
            # colors["select_bg"] fresh on every repaint instead of a
            # value frozen at construction time.
            widget.configure(bg=colors["select_bg"])
        else:
            cls = widget.winfo_class()
            try:
                if cls in ("Toplevel", "Tk"):
                    widget.configure(bg=colors["bg"])  # no -fg option on these
                    if cls == "Toplevel":
                        # This generic repaint walk reaches every open
                        # Toplevel (real children of self.root in Tk's
                        # own widget tree), so hooking the titlebar
                        # refresh here covers Settings/About/Sample
                        # Voices/any future dialog automatically.
                        self._apply_native_titlebar_theme(widget)
                        # dialog_border is theme-tinted (see theme.py),
                        # so it needs reasserting on a live theme switch
                        # same as the titlebar above. Only touches a
                        # Toplevel that already opted into the
                        # bordered-dialog style (highlightthickness > 0).
                        if int(widget.cget("highlightthickness")) > 0:
                            widget.configure(
                                highlightbackground=colors["dialog_border"],
                                highlightcolor=colors["dialog_border"],
                            )
                elif cls == "Frame":
                    # Frame has NO -fg option (only Label does) -- a
                    # combined configure(bg=..., fg=...) here would
                    # throw "unknown option -fg" and get silently
                    # swallowed by the blanket except TclError below.
                    widget.configure(bg=colors["bg"])
                elif cls == "Label":
                    widget.configure(bg=colors["bg"], fg=colors["fg"])
                elif cls == "Panedwindow":
                    widget.configure(bg=colors["bg"])  # no -fg option, same as Toplevel/Tk
                elif cls == "Button":
                    widget.configure(
                        bg=colors["button_bg"], fg=colors["fg"], activebackground=colors["select_bg"]
                    )
                elif cls in ("Checkbutton", "Radiobutton"):
                    # Bare (non-menu) Checkbutton/Radiobutton widgets --
                    # the menu-equivalent checkboxes/radios are Menu
                    # entries (a different code path, "Menu" branch
                    # below). selectcolor (checked-indicator color) is
                    # left alone -- callers pass their own theme-accent
                    # color for it at construction time.
                    #
                    # fixed_theme_name pins bg/active* to a SPECIFIC
                    # theme's own palette (the Theme grid's per-swatch
                    # buttons), matching the fg trace
                    # _wire_toggle_button_contrast already uses -- rather
                    # than painting bg from the dialog's active theme,
                    # which would disagree with the swatch's own fixed fg.
                    _fixed_name = getattr(widget, "slate_fixed_theme_name", None)
                    if _fixed_name:
                        _swatch_colors = theme.get_palette(_fixed_name)
                        _toggle_bg = _swatch_colors["bg"]
                    else:
                        # button_bg is the palette's own designated
                        # "content/card level" tone -- gives unchecked
                        # toggles a real step up from the panel bg
                        # instead of reading as a borderless blob.
                        _swatch_colors = colors
                        _toggle_bg = colors["button_bg"]
                    widget.configure(
                        bg=_toggle_bg, activebackground=_toggle_bg,
                        activeforeground=_swatch_colors["fg"],
                    )
                    if getattr(widget, "slate_toggle_button", False):
                        # fg is owned by _wire_toggle_button_contrast's own
                        # trace (it depends on THIS widget's checked state,
                        # light-on-dark vs dark-on-light varying by theme)
                        # -- re-invoke it here so a THEME switch with no
                        # checked-state change still picks up the new
                        # theme's colors (the trace alone only fires on a
                        # variable write, not a repaint).
                        widget._slate_refresh_toggle_fg()
                    else:
                        widget.configure(fg=colors["fg"])
                elif cls == "Labelframe":
                    widget.configure(bg=colors["bg"], fg=colors["fg"])
                elif cls == "Canvas":
                    widget.configure(bg=colors["canvas_bg"])
                elif cls == "Listbox":
                    widget.configure(
                        bg=colors["entry_bg"], fg=colors["fg"], selectbackground=colors["select_bg"]
                    )
                elif cls in ("Entry", "Text"):
                    widget.configure(
                        bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"]
                    )
                elif cls == "Menu":
                    widget.configure(
                        bg=colors["bg"], fg=colors["fg"],
                        activebackground=colors["select_bg"], activeforeground=colors["fg"],
                    )
            except tk.TclError:
                pass  # some widget/option combos (e.g. Label with no fg option in this state) -- skip, cosmetic only

        for child in widget.winfo_children():
            self._paint_widget(child, colors)

    def _build_menu(self):
        # See RADIO_SELECT_COLOR's own module-level comment. Fixed
        # value, not re-themed live on theme switch (the native Win32
        # menu popup is already a documented can't-fully-control
        # surface, see theme.py's own docstring).
        radio_select_color = RADIO_SELECT_COLOR
        menubar = self.menubar = tk.Menu(self.root)

        filem = self.filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open...", command=self.open_file, accelerator="Ctrl+O")
        self.recent_menu = tk.Menu(filem, tearoff=0, postcommand=self._refresh_recent_menu)
        filem.add_cascade(label="Recent", menu=self.recent_menu)
        filem.add_command(label="Close", command=self.do_close, accelerator="Ctrl+W")
        filem.add_command(label="Save", command=self.save, accelerator="Ctrl+S")
        filem.add_command(label="Save As...", command=self.save_as, accelerator="Ctrl+Shift+S")
        filem.add_separator()
        filem.add_command(label="Merge PDFs...", command=self.do_merge)
        filem.add_command(label="Split into pages...", command=self.do_split)
        filem.add_separator()
        filem.add_command(
            label="Scan folder for sensitive PDFs...", command=self.do_scan_folder
        )
        filem.add_separator()
        filem.add_command(label="Encrypt...", command=self.do_encrypt)
        filem.add_command(label="Sign (self-signed test cert)...", command=self.do_sign)
        filem.add_separator()
        filem.add_command(label="Settings...", command=self._show_settings, accelerator="F12")
        filem.add_separator()
        filem.add_command(label="Quit", command=self.root.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=filem)

        editm = self.editm = tk.Menu(menubar, tearoff=0)
        editm.add_command(label="Copy selected text", command=self._copy_selection, accelerator="Ctrl+C")
        editm.add_separator()
        editm.add_command(label="Redact (drag a region)", command=lambda: self._set_mode("redact"))
        editm.add_command(
            label="Apply pending redactions + Save As...",
            command=self.apply_redactions,
        )
        editm.add_separator()
        editm.add_command(
            label="Scan this document for sensitive content...", command=self.do_scan_document
        )
        editm.add_separator()
        editm.add_command(
            label="Highlight (drag)", command=lambda: self._set_mode("annotate:highlight")
        )
        editm.add_command(
            label="Rectangle (drag)", command=lambda: self._set_mode("annotate:rect")
        )
        editm.add_command(
            label="Freetext note (click)", command=lambda: self._set_mode("annotate:freetext")
        )
        editm.add_command(
            label="Stamp: Approved (click)", command=lambda: self._set_mode("annotate:stamp")
        )
        editm.add_separator()
        editm.add_command(label="Fill form field (click)", command=lambda: self._set_mode("forms"))
        editm.add_separator()
        editm.add_command(
            label="Edit Text (locked, click)...", command=self._start_textedit_mode
        )
        editm.add_separator()
        editm.add_command(label="Back to View mode", command=lambda: self._set_mode("view"))
        menubar.add_cascade(label="Edit", menu=editm)

        viewm = tk.Menu(menubar, tearoff=0)
        viewm.add_checkbutton(
            label="Table of Contents",
            variable=self.toc_visible,
            command=self._toggle_toc_panel,
        )
        viewm.add_separator()
        viewm.add_command(label="Find... (/)", command=self._show_find_bar)
        viewm.add_command(label="Fit Width (Ctrl+0)", command=self.fit_width)
        viewm.add_separator()
        # Independent checkboxes, not mutually-exclusive radio options --
        # matches Adobe/Foxit's own "Two Page View" + "Scroll
        # Continuously" combination.
        self.continuous_scroll_var = tk.BooleanVar(value=self.continuous_scroll)
        self.side_by_side_var = tk.BooleanVar(value=self.side_by_side)
        # Book View: Sumatra-style single toggle that rolls up Continuous
        # Scroll + Side by Side + Fit Width into one F8 press. Derived
        # state, not a third independent axis -- stays in sync with the
        # two underlying checkboxes in both directions (see
        # _set_view_mode).
        self.book_view_var = tk.BooleanVar(value=self.continuous_scroll and self.side_by_side)
        # Settings dialog's own simplified 2-option view -- the View
        # MENU keeps all 3 real checkboxes as independent axes
        # unchanged, but Settings collapses them to one Continuous/Book
        # View choice. Accepted tradeoff: continuous=False+side_by_side=
        # True (side-by-side WITHOUT continuous scroll) has no radio of
        # its own here and reads as "continuous" -- still reachable via
        # the View menu. Kept honest in both directions same as
        # book_view_var (see _set_view_mode).
        self.view_mode_var = tk.StringVar(
            value="book" if (self.continuous_scroll and self.side_by_side) else "continuous"
        )
        layoutmenu = tk.Menu(viewm, tearoff=0)
        layoutmenu.add_checkbutton(
            label="Continuous Scroll", variable=self.continuous_scroll_var,
            command=self._set_view_mode, selectcolor=radio_select_color,
        )
        layoutmenu.add_checkbutton(
            label="Side by Side", variable=self.side_by_side_var,
            command=self._set_view_mode, selectcolor=radio_select_color,
        )
        viewm.add_cascade(label="Page Layout", menu=layoutmenu)
        viewm.add_checkbutton(
            label="Book View (F8)", variable=self.book_view_var,
            command=self._toggle_book_view, selectcolor=radio_select_color,
        )
        viewm.add_separator()
        thememenu = tk.Menu(viewm, tearoff=0)
        for label, name in theme.THEME_LABELS.items():
            thememenu.add_radiobutton(
                label=label, variable=self.theme_name, value=name,
                command=self._on_theme_changed, selectcolor=radio_select_color,
            )
        viewm.add_cascade(label="Theme", menu=thememenu)
        # Opt-out by default: _colorize_for_theme flattens every page to
        # the theme's fg/bg pair, which destroys real color content (a
        # categorical diagram, a photo). A prose-only reader who wants
        # the tinted-to-match-theme look can opt in via this checkbox.
        self.colorize_pages_var = tk.BooleanVar(value=self.colorize_pages)
        viewm.add_checkbutton(
            label="Colorize pages to theme", variable=self.colorize_pages_var,
            command=self._on_colorize_toggle, selectcolor=radio_select_color,
            accelerator="F4",
        )
        # Opt-in same as Colorize above -- a display-altering feature,
        # default off so it doesn't surprise an existing workflow.
        self.crop_to_content_var = tk.BooleanVar(value=self.crop_to_content)
        viewm.add_checkbutton(
            label="Crop to Content", variable=self.crop_to_content_var,
            command=self._on_crop_toggle, selectcolor=radio_select_color,
        )
        viewm.add_separator()
        menubar.add_cascade(label="View", menu=viewm)

        convertm = tk.Menu(menubar, tearoff=0)
        convertm.add_command(label="Export to Markdown...", command=self.do_export_markdown)
        convertm.add_command(label="Export as plain text...", command=self.do_export_text)
        convertm.add_command(label="Export pages as images...", command=self.do_export_images)
        convertm.add_separator()
        convertm.add_command(label="Import images as PDF...", command=self.do_import_images)
        menubar.add_cascade(label="Convert", menu=convertm)

        # Whole menu omitted, not just disabled, when this build excludes
        # the synthesis engine (see tts.ENGINE_AVAILABLE, Slate.spec) --
        # a visible menu that crashes on first click is worse than no
        # menu at all.
        if tts.ENGINE_AVAILABLE:
            readm = tk.Menu(menubar, tearoff=0)
            voicem = tk.Menu(readm, tearoff=0)
            # Bundled voices only -- southern_english_female/danny still
            # exist in tts.VOICES but aren't offered as a pickable
            # default here or in Settings. Downloading one is the only
            # way to try it, left to the user, not a built-in sampler.
            for voice_id, info in tts.VOICES.items():
                if not info.get("bundled"):
                    continue
                voicem.add_radiobutton(
                    label=info["label"], variable=self.tts_voice, value=voice_id,
                    command=self._on_tts_voice_changed, selectcolor=radio_select_color,
                )
            readm.add_cascade(label="Voice", menu=voicem)
            speedm = tk.Menu(readm, tearoff=0)
            for speed in (0.75, 1.0, 1.25, 1.5, 2.0):
                speedm.add_radiobutton(
                    label=f"{speed}x", variable=self.tts_speed, value=speed,
                    command=self._on_tts_speed_changed, selectcolor=radio_select_color,
                )
            readm.add_cascade(label="Speed", menu=speedm)
            readm.add_separator()
            readm.add_separator()
            readm.add_command(label="Read this page", command=self.do_read_page)
            readm.add_command(label="Read entire document", command=self.do_read_document)
            readm.add_command(label="Pause / Resume", command=self.do_tts_pause_resume)
            readm.add_command(label="Stop", command=self.do_tts_stop)
            menubar.add_cascade(label="Read Aloud", menu=readm)

        # Check for Updates lives on the About dialog, not a separate
        # menu item.
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About Slate...", command=self._show_about)
        menubar.add_cascade(label="Help", menu=helpm)

        self.root.config(menu=menubar)

    def _check_for_updates(self, silent_if_current: bool):
        """Real network call, always on a background thread -- same
        thread-safety pattern already established for TTS synthesis/
        voice downloads (never touch Tk widgets off the main thread;
        poll a plain dict via root.after()). silent_if_current=True is
        the startup auto-check -- stays quiet unless there's real news,
        so it never nags on every launch; the menu-triggered manual
        check always reports something, even "up to date" or an
        error."""
        result = {"done": False, "data": None}

        def worker():
            result["data"] = updatecheck.check_for_update(version.VERSION)
            result["done"] = True

        def poll():
            if not result["done"]:
                self.root.after(200, poll)
                return
            data = result["data"]
            if data["update_available"]:
                if messagebox.askyesno(
                    "Update available",
                    f"Slate {data['latest_version']} is available (you have {version.VERSION}).\n\n"
                    f"Open the release page?",
                ):
                    webbrowser.open(data["url"])
            elif not silent_if_current:
                if data["checked"]:
                    messagebox.showinfo("Up to date", f"Slate {version.VERSION} is the latest version.")
                else:
                    messagebox.showinfo("Update check failed", data["error"])

        threading.Thread(target=worker, daemon=True).start()
        poll()

    def _show_command_palette(self, event=None):
        """F2. Theme-switching only for now, but built as a real (label,
        action) list + live filter rather than a theme-only hardcoded
        dialog -- a natural extension point later, not a dead end.
        Escape/click-away cancels; Enter or a click applies the
        highlighted entry and closes."""
        commands = [
            (f"Theme: {label}", (lambda n=name: self._apply_command_palette_theme(n)))
            for label, name in theme.THEME_LABELS.items()
        ]

        top = tk.Toplevel(self.root)
        top.title("Command Palette")
        top.resizable(False, False)
        top.transient(self.root)

        entry_var = tk.StringVar()
        entry = tk.Entry(top, textvariable=entry_var, width=40)
        entry.pack(padx=10, pady=(10, 6), fill=tk.X)
        listbox = tk.Listbox(top, width=40, height=8, activestyle="dotbox")
        listbox.pack(padx=10, pady=(0, 10))

        def refresh(*_a):
            query = entry_var.get().lower()
            listbox.delete(0, tk.END)
            for label, _action in commands:
                if query in label.lower():
                    listbox.insert(tk.END, label)
            if listbox.size() > 0:
                listbox.selection_set(0)

        def run_selected(event=None):
            sel = listbox.curselection()
            if not sel:
                return
            chosen_label = listbox.get(sel[0])
            for label, action in commands:
                if label == chosen_label:
                    action()
                    break
            top.destroy()

        def move_selection(delta):
            if listbox.size() == 0:
                return
            cur = listbox.curselection()
            i = (cur[0] + delta) % listbox.size() if cur else 0
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(i)
            listbox.see(i)

        entry_var.trace_add("write", refresh)
        entry.bind("<Return>", run_selected)
        entry.bind("<Down>", lambda e: move_selection(1))
        entry.bind("<Up>", lambda e: move_selection(-1))
        entry.bind("<Escape>", lambda e: top.destroy())
        listbox.bind("<Double-Button-1>", run_selected)
        top.bind("<Escape>", lambda e: top.destroy())

        refresh()
        self._paint_widget(top, theme.get_palette(self.theme_name.get()))
        entry.focus_set()

        top.update_idletasks()
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        x = root_x + (root_w - top.winfo_width()) // 2
        y = root_y + 60  # near the top, VSCode/Sublime palette convention
        top.geometry(f"+{x}+{y}")

    def _apply_command_palette_theme(self, name):
        self.theme_name.set(name)
        self._on_theme_changed()

    def _show_about(self):
        # Single-instance: re-focus the already-open dialog instead of
        # stacking a second one on repeated menu/button clicks.
        existing = getattr(self, "_about_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        colors = theme.get_palette(self.theme_name.get())
        settings_open = getattr(self, "_settings_window", None)
        if settings_open is not None and not settings_open.winfo_exists():
            settings_open = None
        top = tk.Toplevel(self.root)
        self._about_window = top
        top.title("About Slate")
        top.resizable(False, False)

        def _close_about():
            top.destroy()
            # Hand Settings' grab back if THIS About instance released it
            # on open (settings_open is not None -- see below). Standalone
            # About (settings_open is None) never touched anyone else's
            # grab, so there's nothing to restore in that case.
            if settings_open is not None and settings_open.winfo_exists():
                settings_open.grab_set()

        top.bind("<Escape>", lambda e: _close_about())
        top.protocol("WM_DELETE_WINDOW", _close_about)
        # transient() ties this window to its real opener -- Slate's
        # main window normally, or Settings itself when opened from
        # Settings' own "About Slate..." button (a true parent chain
        # root -> settings -> about, not two siblings both hanging
        # directly off root); -topmost keeps it above every other window.
        top.transient(settings_open if settings_open is not None else self.root)
        top.attributes("-topmost", True)
        # Grab policy: while About is open FROM Settings, NEITHER window
        # holds the grab -- Settings releases its own (so About can
        # receive input/close normally), About never takes one either
        # (so Settings stays fully clickable too). Tk's grab is local to
        # the whole APPLICATION, not the widget that set it, so either
        # window unconditionally grabbing starves the other of input.
        # _close_about above hands Settings' grab back the moment About
        # closes, restoring its normal modal-against-root behavior.
        # About opened standalone (Help menu, no Settings open) stays
        # real modal against root.
        if settings_open is not None:
            settings_open.grab_release()
        else:
            top.grab_set()
        # Titlebar theme handled generically by _paint_widget's own
        # Toplevel branch via the self._paint_widget(top, colors) call
        # below. Visible border, theme-tinted via dialog_border --
        # _paint_widget's Toplevel branch reasserts it on live theme
        # switch, no separate call needed here at construction time.
        top.configure(highlightthickness=2, highlightbackground=colors["dialog_border"], highlightcolor=colors["dialog_border"])

        header = tk.Frame(top)
        header.pack(padx=24, pady=(18, 6), anchor="w")
        if getattr(self, "_icon_img", None) is not None:
            # Same subsample(4,4) reuse-not-reload trick as the home
            # screen's own logo.
            logo = self._icon_img.subsample(4, 4)
            self._about_logo_img = logo  # keep a reference, same gotcha as _tk_img/_home_logo_img
            tk.Label(header, image=logo).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            header, text=f"Slate {version.VERSION}", font=self._ui_header_font(extra=5)
        ).pack(side=tk.LEFT)

        # The ACTIVE theme's own accent, live, via slate_accent_swatch
        # (see _paint_widget's own branch) -- useful precisely because
        # About-from-Settings is non-modal: flip themes in Settings,
        # watch this bar update live.
        accent_bar_row = tk.Frame(top)
        accent_bar_row.pack(fill=tk.X, padx=24, pady=(0, 10))
        theme_accent = tk.Frame(accent_bar_row, height=2)
        theme_accent.slate_accent_swatch = True
        theme_accent.pack(fill=tk.X, expand=True)
        tk.Label(
            top, text=version.SUMMARY, wraplength=360, justify="left"
        ).pack(padx=24, pady=(0, 12))
        author_row = tk.Frame(top)
        author_row.pack(padx=24, pady=(0, 18), anchor="w")
        prefix_label = tk.Label(author_row, text="© 2026 ", fg="gray40")
        prefix_label.slate_muted = True
        prefix_label.pack(side=tk.LEFT)
        # Real hyperlink, not just colored text -- underline + hand
        # cursor is the universal "this is clickable" signal, same
        # convention a browser uses, independent of theme color.
        # tkfont.Font(font=...) properly resolves the widget's actual
        # current default font before adding underline -- cget("font")
        # alone returns a named-font string ("TkDefaultFont"), not
        # something safe to splice into a literal (family, size, style)
        # tuple.
        author_link = tk.Label(author_row, text=version.AUTHOR, fg="gray40", cursor="hand2")
        link_font = tkfont.Font(font=author_link.cget("font"))
        link_font.configure(underline=True)
        author_link.configure(font=link_font)
        author_link.slate_muted = True
        author_link.pack(side=tk.LEFT)
        author_link.bind("<Button-1>", lambda e: webbrowser.open(f"https://github.com/{version.AUTHOR}"))
        button_row = tk.Frame(top)
        button_row.pack(pady=(0, 14))
        # Check for Updates lives here, not a separate Help menu item.
        tk.Button(
            button_row, text="Check for Updates...",
            command=lambda: self._check_for_updates(silent_if_current=False),
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(button_row, text="Close", command=_close_about).pack(side=tk.LEFT)
        self._paint_widget(top, colors)

        # Center over the main window, not the top-left corner -- real
        # geometry only exists after the widgets above are actually laid
        # out, hence update_idletasks() first.
        top.update_idletasks()
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        root_w, root_h = self.root.winfo_width(), self.root.winfo_height()
        dlg_w, dlg_h = top.winfo_width(), top.winfo_height()
        x = root_x + (root_w - dlg_w) // 2
        y = root_y + (root_h - dlg_h) // 2
        top.geometry(f"+{x}+{y}")

    def _show_settings(self):
        """Settings dialog: a single place to see and change every
        persisted preference, modeled on _show_about's own
        Toplevel/accent-bar/centering pattern. Every control here binds
        to the SAME Tk variable and calls the SAME handler the
        corresponding menu item already uses (continuous_scroll_var ->
        _set_view_mode, colorize_pages_var -> _on_colorize_toggle,
        tts_voice/tts_speed -> their existing _on_..._changed handlers)
        -- one source of truth, so this dialog and the menus can never
        drift out of sync. A second place to reach settings that
        already persist via those handlers, not a second mechanism that
        persists them independently."""
        # Single-instance: re-focus the already-open dialog instead of
        # stacking a second one on repeated opens.
        existing = getattr(self, "_settings_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        colors = theme.get_palette(self.theme_name.get())
        top = tk.Toplevel(self.root)
        self._settings_window = top
        top.title("Settings")
        top.resizable(False, False)
        top.bind("<Escape>", lambda e: top.destroy())
        # See _show_about's identical block for the transient/topmost/
        # grab reasoning.
        top.transient(self.root)
        top.attributes("-topmost", True)
        top.grab_set()
        # Titlebar theme handled generically by _paint_widget's own
        # Toplevel branch -- see _show_about's identical comment.
        # Visible border, theme-tinted via dialog_border, no
        # re-assertion needed here at construction time.
        top.configure(highlightthickness=2, highlightbackground=colors["dialog_border"], highlightcolor=colors["dialog_border"])

        header = tk.Frame(top)
        header.pack(padx=24, pady=(18, 6), anchor="w")
        tk.Label(
            header, text="Settings", font=self._ui_header_font(extra=5)
        ).pack(side=tk.LEFT)
        # Same muted-gray treatment as About's own version line, just
        # inline next to the title here instead of its own row.
        version_label = tk.Label(header, text=f"v{version.VERSION}", fg="gray40")
        version_label.slate_muted = True
        version_label.pack(side=tk.LEFT, padx=(8, 0), pady=(4, 0))
        accent_bar = tk.Frame(top, bg="#62a945", height=2)
        accent_bar.slate_fixed_bg = "#62a945"
        accent_bar.pack(fill=tk.X, padx=24, pady=(0, 10))

        # Same THEME_LABELS/self.theme_name/_on_theme_changed the
        # View>Theme submenu already uses, not a second theme picker.
        # _on_theme_changed_and_repaint (below) runs the normal handler
        # (repaints the main window, saves the preference, invalidates
        # the page cache) THEN repaints this still-open dialog too.
        # accent_bar needs no re-assertion here (slate_fixed_bg handles
        # it inside _paint_widget itself).
        #
        # Family dropdown + 2 plain light/dark radios: both real,
        # standard controls -- no custom selection-indicator code,
        # because ttk.Combobox and tk.Radiobutton already show their own
        # selected state natively. A small palette-preview strip keeps
        # the actual colors visible without a big swatch grid.
        #
        # Families derived from THEME_LABELS itself (split on a
        # trailing "Light"/"Dark" word) so a future theme add/remove/
        # rename can't silently drift this out of sync with the real
        # roster.
        theme_frame = tk.LabelFrame(top, text="Theme")
        theme_frame.pack(fill=tk.X, padx=24, pady=(0, 10))

        _families = {}
        for label, name in theme.THEME_LABELS.items():
            if label.endswith(" Light"):
                _families.setdefault(label[: -len(" Light")], {})["Light"] = name
            elif label.endswith(" Dark"):
                _families.setdefault(label[: -len(" Dark")], {})["Dark"] = name
            elif label in ("Light", "Dark"):
                _families.setdefault("Standard", {})[label] = name
            else:
                _families.setdefault(label, {})["Light"] = name
        _family_names = list(_families.keys())  # display order = THEME_LABELS' own insertion order

        _current_family, _current_mode = _family_names[0], "Light"
        for _fam, _modes in _families.items():
            for _mode, _name in _modes.items():
                if _name == self.theme_name.get():
                    _current_family, _current_mode = _fam, _mode

        picker_row = tk.Frame(theme_frame)
        picker_row.pack(fill=tk.X, padx=10, pady=(8, 6))
        tk.Label(picker_row, text="Family:").pack(side=tk.LEFT)
        family_var = tk.StringVar(value=_current_family)
        family_combo = ttk.Combobox(
            picker_row, textvariable=family_var, values=_family_names,
            state="readonly", width=13,
        )
        family_combo.pack(side=tk.LEFT, padx=(6, 18))
        mode_var = tk.StringVar(value=_current_mode)
        mode_frame = tk.Frame(picker_row)
        mode_frame.pack(side=tk.LEFT)

        def _select_theme(*_args):
            modes = _families.get(family_var.get(), {})
            mode = mode_var.get()
            if mode not in modes:
                # Single-mode family (a real future case, not a current
                # one) -- fall back to whatever it actually has rather
                # than a KeyError.
                mode = next(iter(modes))
                mode_var.set(mode)
            self.theme_name.set(modes[mode])
            _on_theme_changed_and_repaint()

        # Light/Dark control uses the same proven indicatoron=False +
        # _wire_toggle_button_contrast pattern the Mode/Display toggles
        # use below (real selectcolor=colors["select_bg"], WCAG-checked
        # checked-state text) rather than a plain indicatoron=True
        # Radiobutton -- a bare Radiobutton relies on Tk's own default
        # selectcolor for its indicator dot, which _paint_widget's
        # generic Radiobutton branch never touches, so the dot stays
        # unthemed against a dark background.
        # flat=True packing (no padding between the two buttons, shared
        # 1px border) reads as one segmented control, not two separate
        # buttons -- the actual "single toggle form object" ask.
        light_btn = tk.Radiobutton(
            mode_frame, text="Light", variable=mode_var, value="Light", command=_select_theme,
            indicatoron=False, relief=tk.RAISED, padx=10, pady=3, selectcolor=colors["select_bg"],
        )
        light_btn.pack(side=tk.LEFT)
        self._wire_toggle_button_contrast(light_btn, mode_var, value="Light")
        dark_btn = tk.Radiobutton(
            mode_frame, text="Dark", variable=mode_var, value="Dark", command=_select_theme,
            indicatoron=False, relief=tk.RAISED, padx=10, pady=3, selectcolor=colors["select_bg"],
        )
        dark_btn.pack(side=tk.LEFT, padx=(1, 0))
        self._wire_toggle_button_contrast(dark_btn, mode_var, value="Dark")
        family_combo.bind("<<ComboboxSelected>>", _select_theme)

        # Palette preview -- "include the color palette somewhere in a
        # classy way." 3 small real color chips (background, chrome,
        # accent), updating live with the picker above. Same
        # slate_fixed_bg convention as every other permanently-colored
        # swatch in this app (About's accent bar, the old theme-grid
        # swatches) -- keeps _paint_widget's generic repaint walk from
        # ever fighting these colors.
        preview_row = tk.Frame(theme_frame)
        preview_row.pack(fill=tk.X, padx=10, pady=(0, 8))
        preview_caption = tk.Label(preview_row, text="Preview:", fg="gray40")
        preview_caption.slate_muted = True
        preview_caption.pack(side=tk.LEFT, padx=(0, 8))
        _preview_chips = []
        for _ in range(3):
            chip = tk.Frame(preview_row, width=26, height=18, highlightthickness=1)
            chip.pack_propagate(False)
            chip.pack(side=tk.LEFT, padx=3)
            _preview_chips.append(chip)

        def _refresh_palette_preview():
            palette = theme.THEMES[self.theme_name.get()]
            colors = (palette["bg"], palette["button_bg"], palette["select_bg"])
            for chip, color in zip(_preview_chips, colors):
                chip.configure(bg=color, highlightbackground=palette["fg"], highlightcolor=palette["fg"])
                chip.slate_fixed_bg = color

        def _on_theme_changed_and_repaint():
            self._on_theme_changed()  # re-themes self.root + any other open Toplevel (About, etc.)
            self._paint_widget(top, theme.get_palette(self.theme_name.get()))  # this dialog + its own titlebar
            _refresh_palette_preview()  # covers every trigger, not just this picker (F2 palette, View menu, ...)

        _refresh_palette_preview()  # initial state -- matches theme_name at dialog-open time

        edit_colors_btn = tk.Button(
            theme_frame, text="Edit Colors...",
            command=lambda: self._show_color_editor(_on_theme_changed_and_repaint),
        )
        edit_colors_btn.pack(anchor="w", padx=10, pady=(0, 8))

        # Mode box (Continuous/Book View radio) removed -- Columns
        # (below, under Zoom) is the sole layout control this dialog
        # exposes; continuous scroll stays the permanent, only reading
        # mode (see _apply_width_based_side_by_side's docstring). The
        # View menu's own Continuous Scroll/Side by Side/Book View
        # checkboxes are UNTOUCHED -- still real, independent axes.

        # Colorize is at the TOP of this group and bound to F4 (see
        # _kb_toggle_colorize) since it's the most frequently toggled.
        display_frame = tk.LabelFrame(top, text="Display")
        display_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
        for text, variable, cmd, pad in (
            ("Colorize pages to theme (F4)", self.colorize_pages_var, self._on_colorize_toggle, (6, 2)),
            ("Crop to Content", self.crop_to_content_var, self._on_crop_toggle, (2, 2)),
            ("Show Table of Contents", self.toc_visible, self._toggle_toc_panel, (2, 2)),
            ("Check for updates on start", self.check_updates_on_start_var, self._on_check_updates_toggle, (2, 6)),
        ):
            btn = tk.Checkbutton(
                display_frame, text=text, variable=variable,
                command=cmd, selectcolor=colors["select_bg"],
                indicatoron=False, relief=tk.RAISED, padx=8, pady=2, anchor="w",
            )
            btn.pack(fill=tk.X, padx=10, pady=pad)
            self._wire_toggle_button_contrast(btn, variable)

        # -- Zoom -- read-only display + the existing commands, not a
        # parallel editable field (avoids a second place zoom state could
        # drift from self.viewer.zoom).
        zoom_frame = tk.LabelFrame(top, text="Zoom")
        zoom_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
        zoom_row = tk.Frame(zoom_frame)
        zoom_row.pack(fill=tk.X, padx=10, pady=6)
        zoom_label = tk.Label(
            zoom_row,
            text=f"Current: {self.viewer.zoom:.2f}x" if self.viewer else "No document open",
        )
        zoom_label.pack(side=tk.LEFT)

        def _refresh_zoom_label():
            if self.viewer:
                zoom_label.config(text=f"Current: {self.viewer.zoom:.2f}x")

        def _zoom_in_and_refresh():
            self.zoom_in()
            _refresh_zoom_label()

        def _zoom_out_and_refresh():
            self.zoom_out()
            _refresh_zoom_label()

        def _fit_width_and_refresh():
            self.fit_width()
            _refresh_zoom_label()

        zoom_btns = tk.Frame(zoom_row)
        zoom_btns.pack(side=tk.RIGHT)
        zoom_state = "normal" if self.viewer else "disabled"
        tk.Button(zoom_btns, text="-", width=2, command=_zoom_out_and_refresh, state=zoom_state).pack(side=tk.LEFT)
        tk.Button(zoom_btns, text="+", width=2, command=_zoom_in_and_refresh, state=zoom_state).pack(side=tk.LEFT, padx=4)
        tk.Button(zoom_btns, text="Fit Width", command=_fit_width_and_refresh, state=zoom_state).pack(side=tk.LEFT)

        # Manual control, same -/+ shape as Zoom above -- a click PINS
        # num_columns (self._columns_pinned), which
        # _apply_width_based_side_by_side and _set_view_mode both check
        # first and skip entirely while set, so a manual pick can't get
        # silently overwritten by the next resize or mode toggle. No
        # "Auto" button -- manual -/+ is the only way to change column
        # count from here; the underlying auto-follow-on-resize still
        # runs until the first manual click pins it (unchanged
        # initial-sizing behavior for a fresh ultrawide window).
        # Column change re-fits zoom to width immediately -- calling
        # fit_width() instead of a plain re-render means the new column
        # count never leaves stale zoom from the OLD layout; fit_width()
        # already renders internally, so no separate render call needed.
        columns_row = tk.Frame(zoom_frame)
        columns_row.pack(fill=tk.X, padx=10, pady=(0, 6))

        columns_label = tk.Label(columns_row, text=f"Columns: {self.num_columns}")
        columns_label.pack(side=tk.LEFT)

        def _refresh_columns_label():
            columns_label.config(text=f"Columns: {self.num_columns}")

        def _columns_dec_and_refresh():
            self._columns_pinned = True
            self.num_columns = max(1, self.num_columns - 1)
            self.fit_width()
            _refresh_columns_label()
            _refresh_zoom_label()

        def _columns_inc_and_refresh():
            self._columns_pinned = True
            self.num_columns = min(6, self.num_columns + 1)
            self.fit_width()
            _refresh_columns_label()
            _refresh_zoom_label()

        columns_btns = tk.Frame(columns_row)
        columns_btns.pack(side=tk.RIGHT)
        tk.Button(
            columns_btns, text="-", width=2, command=_columns_dec_and_refresh, state=zoom_state
        ).pack(side=tk.LEFT)
        tk.Button(
            columns_btns, text="+", width=2, command=_columns_inc_and_refresh, state=zoom_state
        ).pack(side=tk.LEFT, padx=4)

        # Separate from Zoom above: Zoom only affects the rendered PAGE;
        # this affects the app's own chrome -- menus, buttons, labels,
        # tabs, dialogs, TOC. See _apply_ui_font_scale's own docstring
        # for the mechanism (Tk's shared named fonts, not per-widget
        # walking). Shown as a PERCENTAGE of whatever Tk's own native
        # default happened to be on this platform, not a raw point
        # count -- the same relative bump regardless of native baseline.
        font_frame = tk.LabelFrame(top, text="UI Font Size")
        font_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
        font_row = tk.Frame(font_frame)
        font_row.pack(fill=tk.X, padx=10, pady=6)
        base_default_size = abs(self._ui_font_base_sizes.get("TkDefaultFont", 10))

        def _ui_font_pct():
            return round((base_default_size + self.ui_font_scale) / base_default_size * 100)

        font_label = tk.Label(font_row, text=f"Current: {_ui_font_pct()}%")
        font_label.pack(side=tk.LEFT)

        def _ui_font_change_and_refresh(delta):
            self._on_ui_font_scale_change(delta)
            font_label.config(text=f"Current: {_ui_font_pct()}%")
            # Every widget referencing one of the shared named fonts
            # redraws itself automatically the instant the font object's
            # size changes -- that's the whole point of using named
            # fonts instead of per-widget literals. Only this dialog's
            # own OUTER window geometry needs a nudge (Tk never auto-
            # resizes a Toplevel after its initial pack), so newly-bigger
            # text doesn't clip against the old fixed window size.
            top.update_idletasks()
            top.geometry("")

        font_btns = tk.Frame(font_row)
        font_btns.pack(side=tk.RIGHT)
        tk.Button(font_btns, text="-", width=2, command=lambda: _ui_font_change_and_refresh(-1)).pack(side=tk.LEFT)
        tk.Button(font_btns, text="+", width=2, command=lambda: _ui_font_change_and_refresh(1)).pack(side=tk.LEFT, padx=4)
        tk.Button(
            font_btns, text="Reset", command=lambda: _ui_font_change_and_refresh(-self.ui_font_scale)
        ).pack(side=tk.LEFT, padx=(4, 0))

        # -- Read Aloud -- omitted entirely when this build excludes the
        # synthesis engine, same reasoning as _build_menu's Read Aloud cascade.
        if tts.ENGINE_AVAILABLE:
            tts_frame = tk.LabelFrame(top, text="Read Aloud")
            tts_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
            tk.Label(tts_frame, text="Voice:").pack(anchor="w", padx=10, pady=(6, 0))
            voice_row = tk.Frame(tts_frame)
            voice_row.pack(fill=tk.X, padx=10)
            # Bundled voices only here too, same reasoning as the Read Aloud
            # menu's own Voice submenu -- see _build_menu's comment.
            for voice_id, info in tts.VOICES.items():
                if not info.get("bundled"):
                    continue
                btn = tk.Radiobutton(
                    voice_row, text=info["label"], variable=self.tts_voice, value=voice_id,
                    command=self._on_tts_voice_changed, selectcolor=colors["select_bg"],
                    indicatoron=False, relief=tk.RAISED, padx=8, pady=2, anchor="w",
                )
                btn.pack(fill=tk.X, pady=1)
                self._wire_toggle_button_contrast(btn, self.tts_voice, value=voice_id)
            tk.Label(tts_frame, text="Speed:").pack(anchor="w", padx=10, pady=(6, 0))
            speed_row = tk.Frame(tts_frame)
            speed_row.pack(fill=tk.X, padx=10, pady=(0, 6))
            for speed in (0.75, 1.0, 1.25, 1.5, 2.0):
                btn = tk.Radiobutton(
                    speed_row, text=f"{speed}x", variable=self.tts_speed, value=speed,
                    command=self._on_tts_speed_changed, selectcolor=colors["select_bg"],
                    indicatoron=False, relief=tk.RAISED, padx=6, pady=2,
                )
                btn.pack(side=tk.LEFT, padx=(0, 4))
                self._wire_toggle_button_contrast(btn, self.tts_speed, value=speed)

        btn_row = tk.Frame(top)
        btn_row.pack(pady=(0, 16))
        tk.Button(btn_row, text="About Slate...", command=self._show_about).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Close", command=top.destroy).pack(side=tk.LEFT)

        self._paint_widget(top, colors)

        top.update_idletasks()
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        root_w, root_h = self.root.winfo_width(), self.root.winfo_height()
        dlg_w, dlg_h = top.winfo_width(), top.winfo_height()
        x = root_x + (root_w - dlg_w) // 2
        y = root_y + (root_h - dlg_h) // 2
        top.geometry(f"+{x}+{y}")

    # Human-readable label per editable base key, in the order shown --
    # _BASE_KEYS' own order grouped roughly bg-family/text-family/
    # chrome-family instead of alphabetical, easier to scan.
    _COLOR_EDITOR_FIELDS = (
        ("bg", "Background"),
        ("bg2", "Chrome Background (tabs)"),
        ("bg3", "Chrome Background (toolbar)"),
        ("button_bg", "Button Background"),
        ("entry_bg", "Input Field Background"),
        ("canvas_bg", "Page Canvas Background"),
        ("fg", "Text"),
        ("muted_fg", "Muted Text"),
        ("faint_fg", "Faint Text"),
        ("select_bg", "Accent / Selection"),
        ("highlight_bg", "Highlight"),
        ("border", "Border"),
    )

    # theme._CASCADE_KEYS -- normally computed FROM the fields above, but
    # directly editable too (Devin's explicit ask: "full control of the
    # colors of every component of Slate"). Editing one records a live
    # override (theme.update_live) so a later base-color edit above
    # doesn't silently recompute it back. Shown as their own section,
    # below a divider, in _show_color_editor.
    _CHROME_COLOR_EDITOR_FIELDS = (
        ("menubar_bg", "Menu Bar Background"),
        ("menubar_fg", "Menu Bar Text"),
        ("tabstrip_bg", "Tab Strip Background"),
        ("toolbar_bg", "Toolbar Background"),
        ("toolbar_fg", "Toolbar Text"),
        ("active_tab_bg", "Active Tab Background"),
        ("dialog_border", "Dialog Border"),
    )

    _HSL_WHEEL_SIZE = 190
    _HSL_WHEEL_RING = 0.32  # inner-radius fraction -- annulus thickness
    _HSL_BOX_SIZE = 190

    def _hsl_wheel_image(self):
        """Precomputed once (pure hue -> RGB annulus, no S/L dependence)
        and cached on the class -- every color row's picker reuses the
        same wheel image, only the SL box needs regenerating per hue."""
        cached = getattr(SlateApp, "_hsl_wheel_cache", None)
        if cached is not None:
            return cached
        n = self._HSL_WHEEL_SIZE
        cx = cy = n / 2
        outer = n / 2 - 1
        inner = outer * self._HSL_WHEEL_RING
        img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        px = img.load()
        for y in range(n):
            dy = y - cy
            for x in range(n):
                dx = x - cx
                dist = math.hypot(dx, dy)
                if dist < inner or dist > outer:
                    continue
                hue = (math.degrees(math.atan2(dy, dx)) + 360) % 360
                r, g, b = colorsys.hls_to_rgb(hue / 360, 0.5, 1.0)
                px[x, y] = (int(r * 255), int(g * 255), int(b * 255), 255)
        photo = ImageTk.PhotoImage(img)
        SlateApp._hsl_wheel_cache = photo
        return photo

    def _hsl_box_image(self, hue_deg: float):
        """Saturation (x) x Lightness (y, inverted -- top=light) square
        for one fixed hue. Regenerated on every hue change (cheap at
        this size, no caching needed -- a stale cached box for the
        previous hue would be a real correctness bug, not just a
        perf miss)."""
        n = self._HSL_BOX_SIZE
        img = Image.new("RGB", (n, n))
        px = img.load()
        h = hue_deg / 360
        for y in range(n):
            light = 1.0 - y / (n - 1)
            for x in range(n):
                sat = x / (n - 1)
                r, g, b = colorsys.hls_to_rgb(h, light, sat)
                px[x, y] = (int(r * 255), int(g * 255), int(b * 255))
        return ImageTk.PhotoImage(img)

    def _show_hsl_picker(self, initial_hex: str, label: str, on_pick):
        """Real wheel (hue, drag around the ring) + box (saturation x
        lightness, drag inside it, recolored live per the current hue)
        picker -- Devin's explicit ask ("HSL is truly the language of
        colors", "full wheel/box"), not Tk's generic native OS dialog.
        on_pick(hexval) fires on every drag motion, live, same
        continuous-apply philosophy as the rest of this editor -- no
        OK/Cancel, just Close, since every intermediate value is already
        real and already applied by the time you see it."""
        top = tk.Toplevel(self.root)
        top.title(f"Pick: {label}")
        top.resizable(False, False)
        top.transient(self.root)

        r, g, b = self._hex_to_rgb01(initial_hex)
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        state = {"h": h * 360, "s": s, "l": l}

        canvas_frame = tk.Frame(top)
        canvas_frame.pack(padx=16, pady=(16, 8))

        wheel_photo = self._hsl_wheel_image()
        wheel_n = self._HSL_WHEEL_SIZE
        wheel = tk.Canvas(canvas_frame, width=wheel_n, height=wheel_n, highlightthickness=0)
        wheel.grid(row=0, column=0, padx=(0, 16))
        wheel.create_image(0, 0, anchor="nw", image=wheel_photo)
        wheel.image = wheel_photo
        wheel_cursor = wheel.create_oval(0, 0, 0, 0, outline="white", width=2)

        box_n = self._HSL_BOX_SIZE
        box = tk.Canvas(canvas_frame, width=box_n, height=box_n, highlightthickness=0)
        box.grid(row=0, column=1)
        box_image_id = box.create_image(0, 0, anchor="nw")
        # outline flips dark/light by the box cursor's OWN lightness --
        # a fixed white ring (the original build) all but disappears
        # once you drag into the box's own bright top edge, real bug
        # caught in review, not cosmetic (contrast-target discipline
        # this app already holds itself to elsewhere).
        box_cursor = box.create_oval(0, 0, 0, 0, outline="white", width=2)

        preview = tk.Frame(top, height=36, highlightthickness=1)
        preview.pack(fill=tk.X, padx=16, pady=(0, 8))

        readout_var = tk.StringVar()
        tk.Label(top, textvariable=readout_var, font=("Consolas", 10)).pack(padx=16, pady=(0, 12), anchor="w")

        def _current_hex():
            rr, gg, bb = colorsys.hls_to_rgb(state["h"] / 360, state["l"], state["s"])
            return "#" + "".join(f"{round(c * 255):02x}" for c in (rr, gg, bb))

        # Debounces the EXPENSIVE half of on_pick (theme.update_live ->
        # _on_theme_changed -> full app repaint + page cache invalidate +
        # re-render if a doc is open) -- B1-Motion fires far faster than a
        # page re-render can keep up with, and _on_theme_changed's own
        # comment already documents that a theme change is "same cost as
        # a zoom change." The cheap, purely-local half of _redraw (cursor
        # position, preview chip, hex/rgb/hsl readout) stays fully
        # synchronous below -- only the app-wide propagation is throttled,
        # so the picker itself never feels laggy even though the real app
        # behind it updates a beat behind the cursor during a fast drag.
        # ButtonRelease forces one final immediate call so the released
        # value is never left stale by a skipped/cancelled timer.
        _debounce = {"after_id": None}
        _DEBOUNCE_MS = 60

        def _flush_pick(hexval):
            if _debounce["after_id"] is not None:
                top.after_cancel(_debounce["after_id"])
                _debounce["after_id"] = None
            on_pick(hexval)

        def _schedule_pick(hexval):
            if _debounce["after_id"] is not None:
                top.after_cancel(_debounce["after_id"])
            _debounce["after_id"] = top.after(_DEBOUNCE_MS, lambda: _flush_pick(hexval))

        def _redraw(update_box_image=True, immediate=False):
            hexval = _current_hex()
            if update_box_image:
                box_photo = self._hsl_box_image(state["h"])
                box.itemconfigure(box_image_id, image=box_photo)
                box.image = box_photo  # keep a real reference -- Tk drops the image silently otherwise

            outer = wheel_n / 2 - 1
            mid_r = outer * (1 + self._HSL_WHEEL_RING) / 2
            ang = math.radians(state["h"])
            wx = wheel_n / 2 + mid_r * math.cos(ang)
            wy = wheel_n / 2 + mid_r * math.sin(ang)
            wheel.coords(wheel_cursor, wx - 6, wy - 6, wx + 6, wy + 6)

            bx = state["s"] * (box_n - 1)
            by = (1 - state["l"]) * (box_n - 1)
            box.coords(box_cursor, bx - 6, by - 6, bx + 6, by + 6)
            box.itemconfigure(box_cursor, outline="#1a1a1a" if state["l"] > 0.6 else "white")

            preview.configure(bg=hexval)
            preview.slate_fixed_bg = hexval
            rr, gg, bb = (round(c * 255) for c in colorsys.hls_to_rgb(state["h"] / 360, state["l"], state["s"]))
            readout_var.set(
                f"{hexval}   rgb({rr}, {gg}, {bb})   "
                f"hsl({round(state['h'])}°, {round(state['s'] * 100)}%, {round(state['l'] * 100)}%)"
            )
            (_flush_pick if immediate else _schedule_pick)(hexval)

        def _wheel_pick(event, immediate=False):
            dx, dy = event.x - wheel_n / 2, event.y - wheel_n / 2
            state["h"] = (math.degrees(math.atan2(dy, dx)) + 360) % 360
            _redraw(update_box_image=True, immediate=immediate)

        def _box_pick(event, immediate=False):
            state["s"] = min(1.0, max(0.0, event.x / (box_n - 1)))
            state["l"] = min(1.0, max(0.0, 1 - event.y / (box_n - 1)))
            _redraw(update_box_image=False, immediate=immediate)

        wheel.bind("<Button-1>", _wheel_pick)
        wheel.bind("<B1-Motion>", _wheel_pick)
        wheel.bind("<ButtonRelease-1>", lambda e: _wheel_pick(e, immediate=True))
        box.bind("<Button-1>", _box_pick)
        box.bind("<B1-Motion>", _box_pick)
        box.bind("<ButtonRelease-1>", lambda e: _box_pick(e, immediate=True))

        tk.Button(top, text="Close", command=top.destroy).pack(pady=(0, 16))
        _redraw(update_box_image=True, immediate=True)

        top.update_idletasks()
        px, py = self.root.winfo_pointerxy()
        top.geometry(f"+{px + 12}+{py + 12}")

    @staticmethod
    def _hex_to_rgb01(hexval: str):
        hexval = hexval.lstrip("#")
        return tuple(int(hexval[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def _show_color_editor(self, on_change=None):
        """Live theme color editor -- edits theme.THEMES[current name] in
        place and repaints the whole running app on every change (same
        _on_theme_changed() path a normal theme switch already uses, see
        theme.update_live's own docstring). Deliberately NOT modal (no
        grab_set/topmost) -- Devin's explicit ask: the main window must
        stay fully interactable (scroll a real page, switch tabs) while
        this is open, to actually judge a color live against real
        content, not just against this dialog's own preview chips.
        Single-instance like Settings/About: re-focus rather than stack.

        Covers every _BASE_KEYS AND _CASCADE_KEYS color (Devin's explicit
        ask: "full control of the colors of every component of Slate"),
        plus a "Save As New Theme..." action that snapshots the current
        live palette under a brand-new name (theme.save_as_new_theme) --
        the source theme/family is never touched by that action.

        The whole build below is wrapped in a try/except that surfaces
        any exception via messagebox.showerror instead of leaving a
        half-built, blank Toplevel: real pinned bug, Windows-frozen-exe-
        only, not reproducible on Linux/Xvfb (personal/NOW.md, tertiary,
        2026-08-03) -- title bar paints correctly but the content area
        never does. Two earlier theories (slow PIL swatch generation;
        a non-modal-Toplevel paint-timing quirk) were both tried and
        ruled out live. If a real exception is what's actually eating
        the dialog on Windows, this makes it visible instead of another
        guess; if it's something else, this at least rules exceptions
        out for good."""
        existing = getattr(self, "_color_editor_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        name = self.theme_name.get()
        is_custom = theme.is_custom(name)
        family = None
        if not is_custom:
            try:
                family, _mode = theme.family_and_mode(name)
            except KeyError:
                # A future theme family added to THEMES/THEME_LABELS
                # without a matching _FAMILY_JSON entry would otherwise
                # raise here silently -- Tk swallows exceptions from a
                # button command to stderr, invisible in a frozen build
                # with no console. Fail loud and specific instead of a
                # dead button click. (A genuinely custom/user-saved
                # theme is NOT this case -- is_custom() above already
                # routed it around this check; this is only a real gap.)
                messagebox.showerror(
                    "Edit Colors",
                    f"\"{name}\" has no known devs-themes source file mapping "
                    "(theme.py's _FAMILY_JSON table) -- can't open the color "
                    "editor for it. This is a real gap in theme.py, not a "
                    "user error.",
                    parent=self.root,
                )
                return
        label = next((l for l, n in theme.THEME_LABELS.items() if n == name), name)
        colors = theme.get_palette(name)
        all_fields = self._COLOR_EDITOR_FIELDS + self._CHROME_COLOR_EDITOR_FIELDS

        top = None
        try:
            top = tk.Toplevel(self.root)
            self._color_editor_window = top
            top.title(f"Edit Colors — {label}")
            top.resizable(False, False)
            top.bind("<Escape>", lambda e: top.destroy())
            top.configure(highlightthickness=2, highlightbackground=colors["dialog_border"], highlightcolor=colors["dialog_border"])

            header = tk.Frame(top)
            header.pack(padx=24, pady=(18, 6), anchor="w")
            tk.Label(
                header, text=f"Edit Colors — {label}",
                font=self._ui_header_font(extra=5),
            ).pack(side=tk.LEFT)
            accent_bar = tk.Frame(top, bg="#62a945", height=2)
            accent_bar.slate_fixed_bg = "#62a945"
            accent_bar.pack(fill=tk.X, padx=24, pady=(0, 10))

            grid = tk.Frame(top)
            grid.pack(fill=tk.X, padx=24)

            entries = {}
            swatches = {}

            def _apply(key, hexval):
                hexval = hexval.strip()
                if not (hexval.startswith("#") and len(hexval) == 7):
                    return False
                try:
                    int(hexval[1:], 16)
                except ValueError:
                    return False
                theme.update_live(name, key, hexval)
                # Repaints self.root AND every open Toplevel this app
                # owns, including `top` itself -- _paint_widget's
                # recursion through winfo_children() is unconditional,
                # so a second explicit self._paint_widget(top, ...) here
                # would just repaint this dialog twice on every single
                # edit (real, caught in review, not just a style nit --
                # doubles the cost of every keystroke for zero visible
                # difference).
                self._on_theme_changed()
                swatches[key].configure(bg=hexval)
                swatches[key].slate_fixed_bg = hexval
                if on_change is not None:
                    on_change()
                return True

            def _make_row(r, key, label):
                tk.Label(grid, text=label, anchor="w", width=24).grid(row=r, column=0, sticky="w", pady=3)
                swatch = tk.Frame(grid, width=28, height=20, highlightthickness=1, cursor="hand2")
                swatch.grid_propagate(False)
                swatch.grid(row=r, column=1, padx=(6, 6))
                swatches[key] = swatch

                entry_var = tk.StringVar(value=theme.THEMES[name][key])
                entries[key] = entry_var
                entry = tk.Entry(grid, textvariable=entry_var, width=9, font=("Consolas", 10))
                entry.grid(row=r, column=2)

                def _on_entry_commit(_event=None, key=key):
                    if not _apply(key, entry_var.get()):
                        entry_var.set(theme.THEMES[name][key])  # invalid hex -- snap back, don't crash the picker
                entry.bind("<Return>", _on_entry_commit)
                entry.bind("<FocusOut>", _on_entry_commit)

                def _on_pick(hexval, key=key):
                    entry_var.set(hexval)
                    _apply(key, hexval)

                def _on_swatch_click(_event=None, key=key, label=label):
                    self._show_hsl_picker(theme.THEMES[name][key], label, lambda hx, key=key: _on_pick(hx, key))
                swatch.bind("<Button-1>", _on_swatch_click)

            row = 0
            for key, field_label in self._COLOR_EDITOR_FIELDS:
                _make_row(row, key, field_label)
                swatches[key].configure(bg=theme.THEMES[name][key])
                swatches[key].slate_fixed_bg = theme.THEMES[name][key]
                row += 1
            # Section divider -- everything below here is normally
            # COMPUTED from the fields above (theme._with_chrome_cascade),
            # not authored directly. Editing one anyway is a real
            # per-theme override, not a one-off preview (theme.
            # update_live's own docstring) -- it survives a later edit
            # to the base color it would otherwise be derived from.
            tk.Label(
                grid, text="Derived colors (usually set automatically; edit to override)",
                anchor="w", fg="gray40",
            ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 3))
            row += 1
            for key, field_label in self._CHROME_COLOR_EDITOR_FIELDS:
                _make_row(row, key, field_label)
                swatches[key].configure(bg=theme.THEMES[name][key])
                swatches[key].slate_fixed_bg = theme.THEMES[name][key]
                row += 1

            push_var = tk.BooleanVar(value=False)
            if not is_custom:
                # No devs-themes family to sync a custom theme's colors
                # into -- this action only makes sense for a built-in
                # family, so it isn't offered at all when editing one.
                push_check = tk.Checkbutton(
                    top, text="Also push to webUI + Runestone (sync_all.py)",
                    variable=push_var, selectcolor=colors["select_bg"],
                    indicatoron=False, relief=tk.RAISED, padx=8, pady=2,
                )
                push_check.pack(fill=tk.X, padx=24, pady=(14, 6))
                self._wire_toggle_button_contrast(push_check, push_var, value=True)

            status_var = tk.StringVar(value="")
            status_label = tk.Label(top, textvariable=status_var, fg="gray40")
            status_label.slate_muted = True
            status_label.pack(padx=24, anchor="w")

            def _refresh_fields_from_live():
                for key, _label in all_fields:
                    hexval = theme.THEMES[name][key]
                    entries[key].set(hexval)
                    swatches[key].configure(bg=hexval)
                    swatches[key].slate_fixed_bg = hexval

            def _do_save():
                try:
                    if is_custom:
                        theme.save_custom_theme(name)
                        path = theme.CUSTOM_THEMES_FILE
                    else:
                        path = theme.save_family_values(name)
                except (OSError, KeyError, ValueError) as e:
                    status_var.set(f"Save failed: {e}")
                    return
                msg = f"Saved to {path}"
                if not is_custom and push_var.get():
                    sync_script = path.parent.parent / "sync_all.py"
                    result = subprocess.run(
                        [sys.executable, str(sync_script), family],
                        cwd=str(sync_script.parent), capture_output=True, text=True,
                    )
                    msg += " -- synced" if result.returncode == 0 else f" -- sync FAILED: {result.stderr.strip()[:200]}"
                status_var.set(msg)

            def _do_save_as():
                new_name = simpledialog.askstring(
                    "Save As New Theme",
                    "Name for the new theme (Light/Dark added automatically):",
                    parent=top,
                )
                if not new_name:
                    return
                try:
                    new_key = theme.save_as_new_theme(name, new_name)
                except ValueError as e:
                    status_var.set(str(e))
                    return
                self.theme_name.set(new_key)
                self._on_theme_changed()
                top.destroy()
                self._color_editor_window = None
                # Reopen fresh on the new theme -- simplest correct way
                # to get the title, the now-relevant Save/push-checkbox
                # state, and every field consistent, rather than trying
                # to patch this same dialog's widgets in place.
                self._show_color_editor(on_change)

            def _do_reset():
                if is_custom:
                    theme.reload_custom_theme(name)
                else:
                    theme.reload_from_disk(name)
                self._on_theme_changed()
                self._paint_widget(top, theme.get_palette(name))
                _refresh_fields_from_live()
                status_var.set("Reverted to last saved values.")
                if on_change is not None:
                    on_change()

            btn_row = tk.Frame(top)
            btn_row.pack(pady=(6, 16))
            tk.Button(btn_row, text="Save" if is_custom else "Save to devs-themes", command=_do_save).pack(side=tk.LEFT, padx=(0, 8))
            tk.Button(btn_row, text="Save As New Theme...", command=_do_save_as).pack(side=tk.LEFT, padx=(0, 8))
            tk.Button(btn_row, text="Reset", command=_do_reset).pack(side=tk.LEFT, padx=(0, 8))
            tk.Button(btn_row, text="Close", command=top.destroy).pack(side=tk.LEFT)

            self._paint_widget(top, colors)

            top.update_idletasks()
            root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            x = root_x + root_w + 12  # docked beside the main window, not centered over it -- both stay visible/interactable
            y = root_y
            top.geometry(f"+{x}+{y}")
            # Real bug hit live on Windows, not reproducible on
            # Linux/Xvfb: a non-modal Toplevel (no grab_set -- see this
            # method's own docstring on why) repositioned via .geometry()
            # right after creation can come up with its native title bar
            # painted but the client content area never receiving its
            # first WM_PAINT -- Settings/About never hit this because
            # grab_set() forces a real paint cycle as a side effect, this
            # dialog deliberately skips that. update_idletasks() alone
            # only processes geometry/layout, not an actual paint; a full
            # update() plus an explicit lift + focus forces one for real.
            # Tried live on Windows already, retested, did NOT fix the
            # blank-content bug alone -- kept anyway (harmless, and still
            # the theoretically-correct fix for the quirk it targets),
            # see this method's own docstring for the real next step.
            top.update()
            top.lift()
            top.focus_force()
        except Exception:
            if top is not None:
                try:
                    top.destroy()
                except Exception:
                    pass
            self._color_editor_window = None
            messagebox.showerror(
                "Edit Colors",
                "The color editor failed to build:\n\n" + traceback.format_exc(),
                parent=self.root,
            )

    def _refresh_recent_menu(self):
        self.recent_menu.delete(0, "end")
        entries = recent.get_recent()
        if not entries:
            self.recent_menu.add_command(label="(no recent files)", state="disabled")
            return
        for e in entries:
            label = os.path.basename(e["path"])
            self.recent_menu.add_command(
                label=label, command=lambda p=e["path"]: self._open_document(p)
            )

    def _title(self):
        if not self.path:
            return "Slate"
        # sign.is_signed() parses the file as a PDF (pyHanko) -- calling
        # it on an ebook format crashes with "Illegal PDF header".
        # self.path is the ORIGINAL path (tab convention, see
        # _open_document) even for a tab whose actual content came from
        # a converted temp PDF (HTML/image opens, convert.path_to_pdf).
        # Guard on the path's own extension, not just self.doc.is_pdf
        # (which reflects the loaded-in-memory format, already true for
        # a converted HTML doc, and would NOT catch this).
        signed = (
            " [SIGNED]"
            if self.doc is not None
            and self.doc.is_pdf
            and self.path.lower().endswith(".pdf")
            and sign.is_signed(self.path)
            else ""
        )
        return f"Slate — {os.path.basename(self.path)}{signed}"

    def _cursor_for_mode(self, mode: str) -> str:
        """_on_pan_press/_on_pan_release swap to a "fleur" move cursor
        for the duration of an active pan, then restore whatever this
        returns. A distinct cursor per interaction SHAPE, not
        decoration: a drag-to-mark-a-region tool (redact, highlight,
        rect) gets crosshair, the standard convention for precise
        rectangular selection; a single-click-a-spot tool (forms,
        stamp, freetext) gets a pointer hand; plain reading/text-select
        (view, textedit) keeps the I-beam every text app already uses."""
        if mode in ("redact", "annotate:highlight", "annotate:rect"):
            return "crosshair"
        if mode in ("forms", "annotate:stamp", "annotate:freetext"):
            return "hand2"
        return "xterm"  # view, textedit

    def _on_pan_press(self, event):
        """Two middle-button conventions share ButtonPress-2:
        browser-style click-to-autoscroll and drag-to-pan. Which one
        you get is decided at RELEASE (_on_pan_release) by whether the
        mouse actually moved before letting go -- a real drag pans
        (already happened live via scan_dragto during the drag itself,
        this press just arms it), a plain click starts/stops
        autoscroll."""
        if self._autoscroll_active:
            # A click while autoscroll is already running is the
            # cancel gesture (browser convention) -- stop here, don't
            # also arm scan_mark for what would read as a real pan.
            self._stop_autoscroll()
            return
        self._pan_press_pos = (event.x, event.y)
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.config(cursor="fleur")

    def _on_pan_release(self, event):
        if self._autoscroll_active:
            return  # this release belongs to the click that just cancelled it, above
        px, py = self._pan_press_pos or (event.x, event.y)
        moved = ((event.x - px) ** 2 + (event.y - py) ** 2) ** 0.5
        if moved > 4:
            self.canvas.config(cursor=self._cursor_for_mode(self.mode))
        else:
            self._start_autoscroll(px, py)  # anchor at the click's PRESS point, not release

    def _on_canvas_motion(self, event):
        """Tracks the live cursor position for _autoscroll_tick while
        autoscroll is running -- cheap no-op otherwise (autoscroll is
        the only thing that needs plain, no-button mouse movement)."""
        if self._autoscroll_active:
            self._autoscroll_pos = (event.x, event.y)

    def _start_autoscroll(self, x, y):
        self._autoscroll_active = True
        self._autoscroll_anchor = (x, y)
        self._autoscroll_pos = (x, y)
        self.canvas.config(cursor="fleur")
        r = 8
        self._autoscroll_indicator_id = self.canvas.create_oval(
            x - r, y - r, x + r, y + r, outline="gray50", width=2, tags=("autoscroll_indicator",)
        )
        self._autoscroll_tick()

    def _stop_autoscroll(self):
        self._autoscroll_active = False
        if self._autoscroll_after_id is not None:
            self.root.after_cancel(self._autoscroll_after_id)
            self._autoscroll_after_id = None
        if self._autoscroll_indicator_id is not None:
            self.canvas.delete(self._autoscroll_indicator_id)
            self._autoscroll_indicator_id = None
        self.canvas.config(cursor=self._cursor_for_mode(self.mode))

    def _on_escape_cancels_autoscroll(self, event=None):
        """root-level, so it works regardless of focus -- a no-op
        (never returns "break") when autoscroll isn't running, so it
        can't interfere with any other widget's own Escape handling
        (e.g. find_entry's "close the find bar")."""
        if self._autoscroll_active:
            self._stop_autoscroll()

    def _autoscroll_tick(self):
        """Runs every 30ms while autoscroll is active -- scroll speed
        is proportional to how far the CURRENT cursor position has
        drifted from the anchor (click point), zero within a small
        deadzone right at the anchor (lets the cursor sit still
        without drifting the view), same shape as every browser's
        middle-click autoscroll. Converts a target pixel-per-tick
        amount into a scrollregion FRACTION (xview_moveto/yview_moveto
        take 0.0-1.0, not pixels) -- generic across single-page and
        continuous mode, no mode-specific math needed since both
        already keep canvas["scrollregion"] current."""
        if not self._autoscroll_active:
            return
        ax, ay = self._autoscroll_anchor
        cx, cy = self._autoscroll_pos
        dx, dy = cx - ax, cy - ay
        deadzone, ramp, max_px = 10, 150, 25

        def speed(delta):
            if abs(delta) <= deadzone:
                return 0.0
            extra = min(abs(delta) - deadzone, ramp)
            return (extra / ramp) * max_px * (1 if delta > 0 else -1)

        sx, sy = speed(dx), speed(dy)
        # Directional cursor reflects whichever axis is actually
        # dominant right now, updated every tick so it follows the
        # cursor as it moves; "fleur" (four-way) only while sitting
        # inside the deadzone, not yet committed to a direction.
        if sx == 0 and sy == 0:
            cursor = "fleur"
        elif abs(sx) >= abs(sy):
            cursor = "sb_h_double_arrow"
        else:
            cursor = "sb_v_double_arrow"
        self.canvas.config(cursor=cursor)
        if sx or sy:
            try:
                rx0, ry0, rx1, ry1 = (float(v) for v in self.canvas["scrollregion"].split())
                total_w, total_h = rx1 - rx0, ry1 - ry0
                if sx and total_w > 0:
                    self.canvas.xview_moveto(self.canvas.xview()[0] + sx / total_w)
                if sy and total_h > 0:
                    self.canvas.yview_moveto(self.canvas.yview()[0] + sy / total_h)
            except (ValueError, tk.TclError):
                pass  # no real scrollregion yet (e.g. nothing open) -- nothing to scroll
        self._autoscroll_after_id = self.root.after(30, self._autoscroll_tick)

    def _set_mode(self, mode):
        self.mode = mode
        if hasattr(self, "canvas"):
            self.canvas.config(cursor=self._cursor_for_mode(mode))
        if not hasattr(self, "mode_label"):
            return  # called before the toolbar exists yet (early init path)
        if mode == "view":
            # "view" is the mode a reading session is in ~99% of the
            # time -- unpacked entirely (not just blanked) rather than
            # shown empty, so the toolbar shows nothing here at all in
            # the common case.
            self.mode_label.pack_forget()
        elif mode == "redact":
            # Real safety nudge, not just cosmetics: redact is the one
            # mode where a mis-drag has irreversible consequences
            # (DESIGN.md's redaction section) -- the mode indicator
            # should not look identical to every harmless mode.
            self.mode_label.config(
                text=f"mode: {mode}", fg="white", bg="#c0392b", padx=6
            )
            self.mode_label.pack(side=tk.LEFT, padx=12)
        else:
            self.mode_label.config(
                text=f"mode: {mode}", fg="blue", bg=self._mode_label_default_bg, padx=0
            )
            self.mode_label.pack(side=tk.LEFT, padx=12)

    def _require_doc(self) -> bool:
        if self.doc is None:
            messagebox.showinfo("No document", "Open a document first (File > Open).")
            return False
        return True

    # ------------------------------------------------------------------
    # gated text editing (DESIGN.md's "Text editing")
    # ------------------------------------------------------------------
    def _start_textedit_mode(self):
        if not self._require_doc():
            return
        if not gate.is_passphrase_set():
            pw1 = simpledialog.askstring(
                "Set a passphrase",
                "No passphrase is set yet. Set one now to enable text editing:",
                show="*", parent=self.root,
            )
            if not pw1:
                return
            pw2 = simpledialog.askstring(
                "Confirm passphrase", "Confirm passphrase:", show="*", parent=self.root
            )
            if pw1 != pw2:
                messagebox.showinfo("Passphrase mismatch", "Passphrases didn't match. Try again.")
                return
            gate.set_passphrase(pw1)
            self._textedit_unlocked_this_session = True
        elif not self._textedit_unlocked_this_session:
            pw = simpledialog.askstring(
                "Unlock text editing", "Enter passphrase:", show="*", parent=self.root
            )
            if pw is None:
                return
            if not gate.check_passphrase(pw):
                messagebox.showinfo("Incorrect passphrase", "That passphrase is incorrect.")
                return
            self._textedit_unlocked_this_session = True
        self._set_mode("textedit")

    def _handle_textedit_click(self, cx, cy):
        z = self.viewer.zoom
        ox, oy = self._page_offset(self._drag_page)
        px, py = (cx - ox) / z, (cy - oy) / z
        page = self.page
        span = textedit.detect_span(page, fitz.Point(px, py))
        if span is None:
            messagebox.showinfo("No text here", "No text found at that location.")
            return

        tier = textedit.font_safety(self.doc, page, span)
        prompt = "Text:"
        if tier == "substitute-needed":
            prompt += (
                "\n\n(This document's original font can't be reproduced exactly "
                "here -- a close substitute font will be used instead.)"
            )
        new_text = simpledialog.askstring(
            "Edit text", prompt, initialvalue=span["text"], parent=self.root
        )
        if new_text is None:
            return
        try:
            textedit.edit_text(self.doc, page, span, new_text, tier=tier)
        except textedit.TextFitError as e:
            messagebox.showinfo("Text doesn't fit", str(e))
            return
        self.render()

    # ------------------------------------------------------------------
    # home screen
    # ------------------------------------------------------------------
    def _show_home_screen(self):
        if self._doc_view_built:
            self.body_frame.pack_forget()
        if self.home_frame is not None:
            self.home_frame.destroy()

        self.root.title("Slate")
        self.home_frame = tk.Frame(self.root, padx=30, pady=30)
        self.home_frame.pack(fill=tk.BOTH, expand=True)

        # Wrapping everything in one inner frame and packing THAT with
        # anchor="n" (top-CENTER, not top-left) gets live-resize
        # centering for free -- Tk's pack geometry manager recomputes
        # anchor position on every resize automatically, no <Configure>
        # handler needed. fill=Y (vertical only, not X) + expand=True
        # lets `content` still stretch to the window's full height, so
        # the recent-files Listbox below keeps filling available
        # vertical space.
        content = tk.Frame(self.home_frame)
        content.pack(fill=tk.Y, expand=True, anchor="n")

        header = tk.Frame(content)
        header.pack(anchor="w", fill=tk.X)
        if getattr(self, "_icon_img", None) is not None:
            # subsample(4) on a 256x256 source -> a crisp 64x64 logo,
            # cheap (no PIL resize needed, this PhotoImage is already
            # loaded for the window icon -- reused, not reloaded).
            logo = self._icon_img.subsample(4, 4)
            self._home_logo_img = logo  # keep a reference, same gotcha as _tk_img
            tk.Label(header, image=logo).pack(side=tk.LEFT, padx=(0, 12))
        title_box = tk.Frame(header)
        title_box.pack(side=tk.LEFT, anchor="w")
        tk.Label(
            title_box, text=f"Slate {version.VERSION}", font=self._ui_header_font(extra=11)
        ).pack(anchor="w")
        # Full colors["fg"] (plain Label, no slate_muted) -- this is the
        # app's own pitch, the first text a new user reads, so it reads
        # as normal-priority text, not a de-emphasized caption.
        tagline = tk.Label(
            title_box, text=version.SUMMARY, wraplength=460, justify="left"
        )
        tagline.pack(anchor="w", pady=(4, 0))

        tk.Button(content, text="Open...", command=self.open_file).pack(
            anchor="w", pady=(16, 16)
        )

        tk.Label(content, text="Recently viewed", font=self._ui_header_font(extra=3)).pack(
            anchor="w"
        )
        entries = recent.get_recent()
        if not entries:
            no_files_label = tk.Label(content, text="No recently viewed files", fg="gray40")
            no_files_label.slate_muted = True
            no_files_label.pack(anchor="w", pady=6)
        else:
            self._recent_entries = entries
            self._recent_listbox = tk.Listbox(
                content, width=90, height=min(10, len(entries))
            )
            for e in entries:
                name = os.path.basename(e["path"])
                parent = os.path.dirname(e["path"])
                self._recent_listbox.insert("end", f"{name}   —   {parent}")
            self._recent_listbox.pack(fill=tk.BOTH, expand=True, pady=6)
            self._recent_listbox.bind("<Double-Button-1>", self._open_recent_selected)
            self._recent_listbox.bind("<Return>", self._open_recent_selected)
            # Delete/Backspace on the selected row + a right-click
            # "Remove" -- two paths to the same removal. Right-click
            # selects the row under the cursor FIRST (a Listbox doesn't
            # do this by default), so the removal always acts on what
            # was actually clicked, not whatever the previous selection
            # happened to be.
            self._recent_listbox.bind("<Delete>", self._remove_recent_selected)
            self._recent_listbox.bind("<BackSpace>", self._remove_recent_selected)
            self._recent_listbox.bind("<Button-3>", self._show_recent_context_menu)

        # __init__ calls _apply_theme() BEFORE _show_home_screen() ever
        # builds home_frame (nothing to paint yet), and the tab-close-
        # back-to-home path (_close_tab_by_index) has the same gap --
        # self-contained repaint here covers both call sites at once.
        self._paint_widget(self.home_frame, theme.get_palette(self.theme_name.get()))

    def _open_recent_selected(self, event=None):
        """Bound to the home screen's recent-files listbox (double-click
        or Enter). Looks up the real path by LIST INDEX into the exact
        entries list the listbox was built from -- the displayed text
        is 'name — parent dir', not the raw path (real UI/UX pass
        improvement), so this must never parse the display string."""
        sel = self._recent_listbox.curselection()
        if sel:
            self._open_document(self._recent_entries[sel[0]]["path"])

    def _remove_recent_selected(self, event=None):
        """Delete/Backspace on the home screen's recent-files listbox.
        Same index-into-_recent_entries lookup as _open_recent_selected,
        same reason (display text isn't the raw path). Rebuilds the whole
        home screen afterward -- simplest way to keep the listbox and
        self._recent_entries in sync, same pattern _refresh_recent_menu
        already uses for the File>Recent submenu."""
        sel = self._recent_listbox.curselection()
        if sel:
            recent.remove_recent(self._recent_entries[sel[0]]["path"])
            self._show_home_screen()

    def _show_recent_context_menu(self, event):
        """Right-click on a recent-files row. Selects the row under the
        cursor first, since a Listbox doesn't do that on a right-click
        by itself -- without this, a right-click far from the current
        selection would remove the WRONG entry."""
        row = self._recent_listbox.nearest(event.y)
        self._recent_listbox.selection_clear(0, "end")
        self._recent_listbox.selection_set(row)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Open", command=self._open_recent_selected)
        menu.add_command(label="Remove from Recent", command=self._remove_recent_selected)
        self._paint_widget(menu, theme.get_palette(self.theme_name.get()))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # document view (toolbar + canvas + toc panel) -- built once, reused
    # ------------------------------------------------------------------
    def _ensure_doc_view_widgets(self):
        if self._doc_view_built:
            return

        self.body_frame = tk.Frame(self.root)

        # A slim tab strip only -- ttk.Notebook's real per-child-widget
        # display isn't used at all (each "tab" is a never-shown
        # placeholder frame). The single shared toolbar/canvas/find-bar/
        # toc below is what actually renders every tab's content, kept
        # exactly as it already worked pre-tabs; only its state (which
        # Tab's doc/page/mode/etc are loaded into the flat attributes)
        # changes on <<NotebookTabChanged>>. Suckless: reuses everything
        # already built rather than duplicating widgets per tab.
        self.tab_strip = ttk.Notebook(self.body_frame, height=1)
        self.tab_strip.pack(side=tk.TOP, fill=tk.X)
        self.tab_strip.bind("<<NotebookTabChanged>>", self._on_tab_strip_changed)
        self.tab_strip.bind("<Button-2>", self._on_tab_strip_click)
        # See _on_tab_strip_left_click's own docstring for the
        # bbox()-is-broken finding this works around, and why the LAST
        # tab specifically needed it.
        self.tab_strip.bind("<Button-1>", self._on_tab_strip_left_click)

        # 3-column grid, not one flat pack() row -- the only reliable
        # way to get a toolbar element TRULY centered in Tk regardless
        # of how wide the left/right clusters are. Equal weight on
        # columns 0 and 2 makes them absorb any extra window width
        # equally, which keeps column 1 (the page indicator) sitting
        # mathematically centered. Foxit/Acrobat-convention editable
        # page-number box + "of N" (type a number, Enter jumps there),
        # not just static text.
        toolbar = self.toolbar = tk.Frame(self.body_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_columnconfigure(2, weight=1)

        # Columns is the FIRST tool in the toolbar (minus, editable count,
        # plus), Fit Width right after it -- the most frequent controls
        # reading a multi-column document, ahead of page-nav/TTS. "<
        # Prev"/"Next >" removed -- duplicates of the ◀/▶ glyph buttons
        # already flanking the page-number box in toolbar_center below
        # (same self.prev/next commands). "Zoom -"/"Zoom +" removed --
        # still reachable via Settings' own Zoom row -/+ buttons and
        # Ctrl+scroll. All three column controls call fit_width() after
        # changing num_columns, same re-fit-on-column-change behavior as
        # Settings' own controls.
        toolbar_left = tk.Frame(toolbar)
        toolbar_left.grid(row=0, column=0, sticky="w")
        tk.Label(toolbar_left, text="Columns:").pack(side=tk.LEFT, padx=(0, 4))

        def _toolbar_columns_dec():
            self._columns_pinned = True
            self.num_columns = max(1, self.num_columns - 1)
            self.fit_width()

        def _toolbar_columns_inc():
            self._columns_pinned = True
            self.num_columns = min(6, self.num_columns + 1)
            self.fit_width()

        tk.Button(toolbar_left, text="-", width=2, command=_toolbar_columns_dec).pack(side=tk.LEFT)
        # Real, editable count, not a read-only label -- Enter applies a
        # typed value directly (same "type a number, Enter jumps/applies"
        # convention as the page-number box in toolbar_center). Synced
        # to self.num_columns on every render() (see its own tail), same
        # place page_entry_var/page_total_label already refresh from.
        self.columns_entry_var = tk.StringVar(value=str(self.num_columns))
        columns_entry = tk.Entry(toolbar_left, textvariable=self.columns_entry_var, width=3, justify="center")
        columns_entry.pack(side=tk.LEFT, padx=2)
        columns_entry.bind("<Return>", self._on_columns_entry)
        tk.Button(toolbar_left, text="+", width=2, command=_toolbar_columns_inc).pack(side=tk.LEFT, padx=(0, 12))
        tk.Button(toolbar_left, text="Fit Width", command=self.fit_width).pack(side=tk.LEFT)
        # See _set_mode below: only packs itself into the toolbar for a
        # non-view mode, unpacking (not just blanking text) back to
        # view, so the common case shows nothing here at all.
        self.mode_label = tk.Label(toolbar_left, text="", fg="blue")
        self._mode_label_default_bg = self.mode_label.cget("bg")

        toolbar_center = tk.Frame(toolbar)
        toolbar_center.grid(row=0, column=1)
        # Small prev/next glyph buttons flank the page box -- the
        # typed-number-jumps-straight-there behavior is untouched, this
        # is an ADDITIONAL click path for the common "just go one page"
        # case.
        tk.Button(
            toolbar_center, text="◀", command=self.prev, width=2, padx=0,
        ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(toolbar_center, text="Page").pack(side=tk.LEFT, padx=(0, 4))
        self.page_entry_var = tk.StringVar(value="1")
        self.page_entry = tk.Entry(toolbar_center, width=4, textvariable=self.page_entry_var, justify="center")
        self.page_entry.pack(side=tk.LEFT)
        self.page_entry.bind("<Return>", self._goto_page_entry)
        self.page_total_label = tk.Label(toolbar_center, text="of 1")
        self.page_total_label.pack(side=tk.LEFT, padx=(4, 6))
        tk.Button(
            toolbar_center, text="▶", command=self.next, width=2, padx=0,
        ).pack(side=tk.LEFT)

        toolbar_right = tk.Frame(toolbar)
        toolbar_right.grid(row=0, column=2, sticky="e")
        self.status = tk.Label(toolbar_right, text="")
        self.status.pack(side=tk.RIGHT, padx=8)
        # Read Aloud quick-access controls, also reachable via the Read
        # Aloud menu. Two buttons: one smart play/pause/resume toggle
        # (do_tts_toggle_play decides which action makes sense for the
        # current state) plus a stop, same real actions the menu
        # already exposes, not a separate mechanism. Omitted entirely
        # when this build excludes the synthesis engine -- every caller
        # (_update_tts_toolbar_button, _update_tts_ui) already guards on
        # hasattr(self, "tts_play_button"/"tts_status_label") for the
        # home-screen-has-no-toolbar-yet case, so their absence here is
        # already a handled state, not a new one.
        if tts.ENGINE_AVAILABLE:
            self.tts_stop_button = tk.Button(toolbar_right, text="⏹", width=2, padx=0, command=self.do_tts_stop)
            self.tts_stop_button.pack(side=tk.RIGHT, padx=(0, 6))
            self.tts_play_button = tk.Button(
                toolbar_right, text="▶", width=2, padx=0, command=self.do_tts_toggle_play,
            )
            self.tts_play_button.pack(side=tk.RIGHT, padx=(0, 2))
            # Fixed green accent regardless of theme -- same convention as
            # the About dialog's permanent accent bar, empty text (so no
            # layout gap) whenever nothing's actually loaded.
            self.tts_status_label = tk.Label(toolbar_right, text="", fg="#62a945")
            self.tts_status_label.pack(side=tk.RIGHT, padx=(0, 8))

        self.find_frame = tk.Frame(self.body_frame)
        tk.Label(self.find_frame, text="Find:").pack(side=tk.LEFT, padx=(6, 4))
        self.find_var = tk.StringVar()
        find_entry = tk.Entry(self.find_frame, textvariable=self.find_var, width=30)
        find_entry.pack(side=tk.LEFT)
        find_entry.bind("<Return>", self._find_next)
        find_entry.bind("<Shift-Return>", self._find_prev)
        find_entry.bind("<Escape>", lambda e: self._hide_find_bar())
        self.find_status = tk.Label(self.find_frame, text="")
        self.find_status.pack(side=tk.LEFT, padx=8)
        tk.Button(self.find_frame, text="X", command=self._hide_find_bar).pack(side=tk.RIGHT, padx=6)
        self._find_entry = find_entry
        # not packed by default -- toggled via "/" or View > Find...

        # PanedWindow, not a plain Frame -- gives the TOC/canvas split a
        # real drag-to-resize sash for free via Tk's own built-in
        # mechanism, rather than hand-rolling drag math.
        content = tk.PanedWindow(self.body_frame, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._content_frame = content

        self.toc_frame = tk.Frame(content, width=240)
        self.toc_tree = ttk.Treeview(self.toc_frame, show="tree")
        self.toc_tree.pack(fill=tk.BOTH, expand=True)
        self.toc_tree.bind("<<TreeviewSelect>>", self._on_toc_select)
        # not added to the PanedWindow by default -- toggled via
        # View > Table of Contents (content.add/.forget, see
        # _toggle_toc_panel -- PanedWindow's own show/hide, not pack)

        # canvas_frame holds canvas + both scrollbars together (grid,
        # not pack -- the standard Tk 2x2 canvas/scrollbar layout) so
        # the PAIR can be added to the PanedWindow as one pane.
        canvas_frame = tk.Frame(content)
        # highlightthickness=0/bd=0: Tk's default 1px focus-highlight
        # border was silently offsetting every canvasx()/canvasy()
        # click-to-pdf coordinate conversion by 1px -- invisible before
        # render() forced update_idletasks() (real geometry realization
        # made the border inset apply consistently instead of by luck).
        self.canvas = tk.Canvas(canvas_frame, bg="gray80", highlightthickness=0, bd=0)
        # elementborderwidth: tk.Scrollbar's default (-1, "inherit from
        # borderwidth") defers to Windows' own native XP-theme scrollbar
        # renderer, different from the classic beveled Motif-style
        # arrows the same widget code renders under real Linux Tk (WSLg).
        # Setting it explicitly forces Tk's own portable/classic
        # rendering path on every platform -- same widget, same look,
        # regardless of OS. Not confirmed on a real Windows desktop (no
        # window manager in this Linux sandbox).
        self._vscroll = tk.Scrollbar(
            canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview, elementborderwidth=2
        )
        self._hscroll = tk.Scrollbar(
            canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview, elementborderwidth=2
        )
        # yscrollcommand SHOULD fire on every y-view change regardless
        # of cause, but a plain yview_moveto()/scrollbar-drag doesn't
        # reliably trigger it in this dev box's headless Xvfb, even
        # after root.update() -- kept as a belt-and-suspenders hook, but
        # continuous mode's page-number sync does NOT depend on it alone
        # (see the explicit _sync_page_num_from_scroll() calls in the
        # wheel handlers and the scrollbar-drag bindings just below).
        self.canvas.configure(yscrollcommand=self._on_canvas_yscroll, xscrollcommand=self._hscroll.set)
        self._vscroll.bind("<B1-Motion>", self._sync_page_num_from_scroll)
        self._vscroll.bind("<ButtonRelease-1>", self._sync_page_num_from_scroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")
        self._hscroll.grid(row=1, column=0, sticky="ew")
        # A real drag-to-resize grip (standard OS bottom-right window
        # resize convention) with a bigger-than-default hitbox (22px vs
        # a plain scrollbar's ~17px) instead of the usual bare diagonal
        # hatch -- see _draw_corner_grip for the rune icon rendered here.
        self._corner_grip = tk.Canvas(
            canvas_frame, width=22, height=22, highlightthickness=0, bd=0, cursor="bottom_right_corner",
        )
        self._corner_grip.grid(row=1, column=1, sticky="nsew")
        self._corner_grip.bind("<ButtonPress-1>", self._on_corner_grip_press)
        self._corner_grip.bind("<B1-Motion>", self._on_corner_grip_drag)
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        self._canvas_frame = canvas_frame  # _toggle_toc_panel needs the PANE widget, not the bare canvas
        content.add(canvas_frame, stretch="always")
        # Real width-based auto layout on top of the manual checkbox,
        # not a replacement for it (see _on_canvas_frame_configure).
        canvas_frame.bind("<Configure>", self._on_canvas_frame_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Right-click = context menu, view mode only -- see
        # _show_canvas_context_menu's own docstring for why and what's
        # in it.
        self.canvas.bind("<Button-3>", self._show_canvas_context_menu)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<Motion>", self._on_canvas_motion)

        # All routed through the same guarded _kb_prev_page/_kb_next_page
        # as j/k below, so e.g. pressing Left to move the text cursor
        # while typing in the Find box doesn't ALSO flip a page
        # underneath it.
        self.root.bind("<Left>", self._kb_prev_page)
        self.root.bind("<Right>", self._kb_next_page)
        self.root.bind("<Up>", self._kb_prev_page)
        self.root.bind("<Down>", self._kb_next_page)
        self.root.bind("<Prior>", self._kb_prev_page)  # Page Up
        self.root.bind("<Next>", self._kb_next_page)  # Page Down
        # Home/End = first/last page, same handlers vim-style g/G already
        # use below -- Home/End is the more universal Adobe/Foxit/Sumatra
        # convention, this was just never bound to it.
        self.root.bind("<Home>", self._kb_first_page)
        self.root.bind("<End>", self._kb_last_page)
        # Mouse wheel: Windows/Mac deliver <MouseWheel> with a signed
        # event.delta; X11/Linux (this dev environment) instead sends
        # discrete Button-4 (up) / Button-5 (down) click events with no
        # delta at all -- both bound so this is actually testable here,
        # not just assumed to work on the real deployment target. Both
        # now route through _wheel_up/_wheel_down -- previously Button-4/5
        # bypassed _on_mouse_wheel entirely and called page-nav directly, a
        # real X11/Windows parity gap that only happened to be invisible
        # because both paths did the exact same unconditional thing.
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", self._wheel_up)
        self.canvas.bind("<Button-5>", self._wheel_down)
        # Ctrl+scroll = zoom, same platform split as plain wheel above --
        # Tk's compound event names route the Control-modified wheel to a
        # separate binding automatically, no manual event.state check needed.
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mouse_wheel)
        self.canvas.bind("<Control-Button-4>", lambda e: self.zoom_in())
        self.canvas.bind("<Control-Button-5>", lambda e: self.zoom_out())
        # Shift+scroll = horizontal scroll, same platform split as
        # Ctrl+scroll above.
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mouse_wheel)
        self.canvas.bind("<Shift-Button-4>", self._shift_wheel_left)
        self.canvas.bind("<Shift-Button-5>", self._shift_wheel_right)

        # Sumatra-style keyboard nav. Guarded on "typing somewhere" (any
        # Entry has focus, e.g. the find box itself) so these don't
        # hijack normal text entry -- a real risk since single-letter
        # keys like "j"/"g" are otherwise perfectly valid search text.
        self.root.bind("<Key-j>", self._kb_next_page)
        self.root.bind("<Key-k>", self._kb_prev_page)
        self.root.bind("<Key-g>", self._kb_first_page)
        self.root.bind("<Key-G>", self._kb_last_page)
        self.root.bind("<Key-n>", self._kb_find_next)
        self.root.bind("<Key-N>", self._kb_find_prev)
        self.root.bind("<Key-slash>", self._kb_open_find)
        self.root.bind("<Control-c>", self._copy_selection)
        self.root.bind("<F8>", self._kb_toggle_book_view)
        self.root.bind("<F4>", self._kb_toggle_colorize)

        # CUA keybinds -- the standard Windows/Mac shortcut set, matching
        # menu accelerators added alongside these.
        self.root.bind("<F2>", self._show_command_palette)
        self.root.bind("<F12>", lambda e: self._show_settings())
        self.root.bind("<Control-w>", lambda e: self.do_close())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.bind("<Control-S>", lambda e: self.save_as())  # Ctrl+Shift+S
        self.root.bind("<Control-f>", self._kb_open_find)  # alongside "/", not a replacement
        self.root.bind("<Control-q>", lambda e: self.root.quit())
        self.root.bind("<Control-plus>", lambda e: self.zoom_in())
        self.root.bind("<Control-equal>", lambda e: self.zoom_in())  # Ctrl+= (no-Shift + key, most keyboards)
        self.root.bind("<Control-minus>", lambda e: self.zoom_out())
        self.root.bind("<Control-0>", lambda e: self.fit_width())
        self.root.bind("<Control-Tab>", self._kb_next_tab)
        self.root.bind("<Control-Shift-Tab>", self._kb_prev_tab)
        self.root.bind("<Control-Next>", self._kb_next_tab)  # Ctrl+PageDown, browser-tab convention
        self.root.bind("<Control-Prior>", self._kb_prev_tab)  # Ctrl+PageUp
        self.root.bind("<Escape>", self._on_escape_cancels_autoscroll)

        self._doc_view_built = True
        # These widgets are built lazily, on first document open --
        # _apply_theme() only ran once already, in __init__, BEFORE any
        # of them existed (their constructors' hardcoded defaults, e.g.
        # the canvas's bg="gray80", would otherwise silently stick
        # forever for an app launched directly with a path).
        self._apply_theme()
        # The BooleanVar itself defaults True (__init__), but nothing
        # actually added the panel to the PanedWindow until now;
        # _toggle_toc_panel needs toc_frame/_canvas_frame, both real
        # only once this method has run this far.
        if self.toc_visible.get():
            self._toggle_toc_panel()

    def _typing_in_entry(self) -> bool:
        return isinstance(self.root.focus_get(), tk.Entry)

    def _kb_next_page(self, event=None):
        if self._typing_in_entry():
            return
        self.next()

    def _kb_prev_page(self, event=None):
        if self._typing_in_entry():
            return
        self.prev()

    def _reset_scroll(self):
        """A fresh page should start showing from the top-left, not
        wherever the previous page happened to be scrolled to -- only
        called from real page-NAVIGATION sites, never from render()
        itself (which also fires for same-page redraws like adding an
        annotation, where jumping the scroll position would be
        jarring, not helpful)."""
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _scroll_to_page(self, page_num):
        """Continuous mode's equivalent of _reset_scroll(): scroll so
        this page's top edge lands at the viewport top, rather than
        jumping to canvas-origin (0, 0) -- page N's top isn't the
        canvas origin once every page is stacked in one scrollable
        canvas."""
        if self._layout is None:
            return
        _x0, y0, _x1, _y1 = self._layout.rect_of(page_num)
        _total_w, total_h = self._layout.total_size
        if total_h <= 0:
            return
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(y0 / total_h)

    def _go_to_page(self, page_num):
        """Shared real-navigation path (page-box/first/last/TOC-select
        all funnel through this): jump + clear the old page's
        selection + render, landing at that page's top -- single-page
        mode via _reset_scroll() (unchanged), continuous mode via
        _scroll_to_page() (this page's real canvas-space top, not the
        canvas origin)."""
        self.viewer.goto(page_num)
        self._selected_words = []
        self.render()
        if self.continuous_scroll:
            self._scroll_to_page(self.viewer.page_num)
        else:
            self._reset_scroll()
        # Plain scrolling in continuous mode also moves page_num (see
        # _sync_page_num_from_scroll) but isn't checkpointed here on
        # purpose -- that fires on every scroll tick, and writing
        # settings.json that often is needless I/O; window close
        # (main()'s _on_close) does one final save covering wherever
        # scrolling actually left things.
        self._save_open_tabs()

    def _on_canvas_yscroll(self, first, last):
        """The canvas's yscrollcommand -- fires on every y-view change
        regardless of cause (wheel, scrollbar drag, programmatic
        yview_moveto). Updates the real scrollbar (its previous, only
        job) and, in continuous mode, keeps viewer.page_num/the page
        box in sync with whatever's actually visible."""
        self._vscroll.set(first, last)
        self._sync_page_num_from_scroll()

    def _sync_page_num_from_scroll(self, event=None):
        """Continuous mode only: the page-number box/TOC highlight
        should track whatever page is at the viewport's top edge while
        scrolling, not freeze at whatever page was current when
        continuous mode was entered. Also the one real trigger point
        for _shift_window -- every organic scroll cause (wheel,
        scrollbar drag, yscrollcommand) already funnels through here, so
        windowing piggybacks on the same hook rather than needing its
        own."""
        if self._suppress_scroll_sync:
            return
        if not self.continuous_scroll or self._layout is None or self.viewer is None:
            return
        first, _last = self.canvas.yview()
        _total_w, total_h = self._layout.total_size
        top_y = first * total_h
        page_num = self._layout.topmost_visible(top_y)
        if page_num != self.viewer.page_num:
            self.viewer.goto(page_num)
            self.page_entry_var.set(str(self.viewer.page_num + 1))
        self._shift_window()

    def _set_view_mode(self):
        """Page Layout submenu (View menu) -- Continuous Scroll and Side
        by Side are independent checkboxes, not mutually-exclusive
        radio options."""
        self.continuous_scroll = self.continuous_scroll_var.get()
        self.side_by_side = self.side_by_side_var.get()
        # Canonical entry point for the plain 2-vs-1 meaning num_columns
        # has always had -- every caller that flips side_by_side_var and
        # calls _set_view_mode() directly gets the right column count
        # without needing its own num_columns line.
        # _apply_width_based_side_by_side (ultrawide auto-follow) is the
        # ONE other case that wants a count above 2 -- it deliberately
        # overrides this again, AFTER calling here, for that case only.
        # Skipped entirely while pinned -- a Continuous/Book View mode
        # switch shouldn't silently stomp a manually-chosen column count.
        if not self._columns_pinned:
            self.num_columns = 2 if self.side_by_side else 1
        settings.save({"continuous_scroll": self.continuous_scroll, "side_by_side": self.side_by_side})
        # Keep Book View's own checkbox honest even when the user toggles
        # the two underlying boxes individually rather than via F8/the
        # Book View item -- it should only show checked when BOTH
        # underlying axes actually agree, never a stale/independent guess.
        self.book_view_var.set(self.continuous_scroll and self.side_by_side)
        self.view_mode_var.set("book" if (self.continuous_scroll and self.side_by_side) else "continuous")
        self._render_current_layout()

    def _render_current_layout(self):
        """Shared re-render + scroll-position-fix tail so
        _apply_width_based_side_by_side can reuse it after overriding
        num_columns past what _set_view_mode's own 2-vs-1 default just
        set, without duplicating the scroll-fix logic."""
        if self.viewer is None:
            return
        self._selected_words = []
        self.render()
        if self.continuous_scroll:
            self._scroll_to_page(self.viewer.page_num)
        else:
            self._reset_scroll()

    def _toggle_book_view(self):
        """One combined preset (Sumatra-naming) instead of setting
        Continuous Scroll + Side by Side by hand every time. Reads
        book_view_var's OWN new value (already flipped by Tk before this
        command fires, same as any checkbutton) and pushes that value
        onto both real axes, then reuses _set_view_mode's existing
        save/render/scroll path -- no duplicated logic. Fit Width
        included; a centered alignment isn't built yet."""
        want = self.book_view_var.get()
        self.continuous_scroll_var.set(want)
        self.side_by_side_var.set(want)
        self._set_view_mode()  # also sets num_columns (2-vs-1) from side_by_side, see its own comment
        if want:
            self.fit_width()

    def _kb_toggle_book_view(self, event=None):
        """F8 -- same effect as clicking the Book View checkbutton, but a
        raw key press doesn't flip book_view_var itself first (Tk only
        does that for an actual Checkbutton widget click), so flip it
        here before reusing _toggle_book_view's real logic."""
        self.book_view_var.set(not self.book_view_var.get())
        self._toggle_book_view()
        return "break"

    def _kb_toggle_colorize(self, event=None):
        """F4 -- same raw-keypress-needs-a-manual-flip-first pattern as
        F8/_kb_toggle_book_view, reusing _on_colorize_toggle's real
        cache-invalidate-and-render logic rather than duplicating it."""
        self.colorize_pages_var.set(not self.colorize_pages_var.get())
        self._on_colorize_toggle()

    def _select_view_mode_continuous(self):
        """Settings dialog's simplified "Continuous" radio -- plain
        single-column continuous scroll, side_by_side off. Reuses
        _set_view_mode's existing save/render/scroll path via the same
        two underlying Tk vars the View menu's real checkboxes use, so
        this dialog can never drift from the menu's own state."""
        self.continuous_scroll_var.set(True)
        self.side_by_side_var.set(False)
        self._set_view_mode()

    def _select_view_mode_book(self):
        """Settings dialog's simplified "Book View" radio -- reuses
        _toggle_book_view's real logic (which also runs Fit Width)
        rather than duplicating it."""
        self.book_view_var.set(True)
        self._toggle_book_view()

    def _on_canvas_frame_configure(self, event=None):
        """<Configure> fires continuously during a live drag-resize (and
        once per render()'s own canvas resize) -- debounced via
        after_cancel/after so the real width check only runs once
        resizing actually settles, not on every intermediate pixel."""
        if self._autolayout_after_id is not None:
            self.root.after_cancel(self._autolayout_after_id)
        self._autolayout_after_id = self.root.after(150, self._apply_width_based_side_by_side)

    def _apply_width_based_side_by_side(self):
        """Real width threshold, not a guess: each additional column at
        the CURRENT zoom costs one more page-width + one more inter-page
        gap. continuous_scroll is never touched here -- only the column
        count auto-follows width. Computes however many whole columns
        actually fit, capped at 6 -- past that, per-column width gets
        uncomfortably narrow for reading regardless of how much raw
        pixel width is available. self.side_by_side (plain bool) stays
        in sync as "num_columns >= 2" purely for the View menu's
        existing "Side by Side" checkbox + settings.json persistence --
        num_columns, not this bool, is what every render call site
        actually reads.

        self._columns_pinned (Settings' own Columns -/+ control)
        short-circuits this entirely while set -- a manual pick stops
        being silently overwritten by the next resize."""
        self._autolayout_after_id = None
        if self._columns_pinned or self.viewer is None or self.doc is None:
            return
        available_w = self._canvas_frame.winfo_width()
        page_w = self.doc[0].rect.width * self.viewer.zoom
        gap = self._layout.gap if self._layout is not None else 8
        new_cols = max(1, min(6, int((available_w + gap) // (page_w + gap))))
        if new_cols == self.num_columns:
            return
        should_be_side_by_side = new_cols >= 2
        if should_be_side_by_side != self.side_by_side_var.get():
            self.side_by_side_var.set(should_be_side_by_side)
            # _set_view_mode() also resets num_columns to its own plain
            # 1-or-2 default as a side effect (see its comment) -- fine,
            # overridden with the real count right after, before the
            # actual render happens below.
            self._set_view_mode()
        self.num_columns = new_cols
        self._render_current_layout()

    def _goto_page_entry(self, event=None):
        """Foxit/Acrobat convention: type a page number into the
        centered box, Enter jumps there. Invalid/out-of-range input
        fails soft -- reverts the box to the real current page rather
        than crashing or silently doing nothing with no feedback."""
        if self.viewer is None:
            return
        try:
            n = int(self.page_entry_var.get())
        except ValueError:
            n = self.viewer.page_num + 1  # not a number -- revert, see below
        n = max(1, min(self.viewer.page_count, n))
        self._go_to_page(n - 1)

    def _on_columns_entry(self, event=None):
        """Same fail-soft convention as _goto_page_entry: invalid/out-of-
        range input reverts the box to the real current count rather
        than crashing or silently doing nothing. A typed value is a
        manual pick same as the -/+ buttons -- pins columns and re-fits."""
        if self.viewer is None:
            return
        try:
            n = int(self.columns_entry_var.get())
        except ValueError:
            n = self.num_columns  # not a number -- revert, see below
        n = max(1, min(6, n))
        self._columns_pinned = True
        self.num_columns = n
        self.fit_width()

    def _kb_first_page(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self._go_to_page(0)

    def _kb_last_page(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self._go_to_page(self.viewer.page_count - 1)

    def _kb_open_find(self, event=None):
        if self._typing_in_entry():
            return  # let a literal "/" be typed into whatever entry has focus
        self._show_find_bar()
        return "break"

    def _kb_find_next(self, event=None):
        """Root-level "n" binding -- guarded so typing a literal 'n' into
        the find box (or any other entry) doesn't also trigger a jump."""
        if self._typing_in_entry():
            return
        self._find_next()

    def _kb_find_prev(self, event=None):
        if self._typing_in_entry():
            return
        self._find_prev()

    # ------------------------------------------------------------------
    # find / search
    # ------------------------------------------------------------------
    def _show_find_bar(self):
        if not self._require_doc():
            return
        self.find_frame.pack(side=tk.TOP, fill=tk.X, before=self._content_frame)
        self._find_entry.focus_set()

    def _hide_find_bar(self):
        self.find_frame.pack_forget()
        self.canvas.focus_set()

    def _run_find(self):
        query = self.find_var.get()
        self.search_state.run(self.doc, query)
        n = len(self.search_state.matches)
        if not query.strip():
            self.find_status.config(text="")
        elif n == 0:
            self.find_status.config(text="no matches")
        else:
            self.find_status.config(text=f"1/{n}")
        return n

    def _jump_to_current_match(self):
        match = self.search_state.current()
        if match is None:
            return
        page_num, _rect = match
        if self.viewer.page_num != page_num:
            self._go_to_page(page_num)
        else:
            self.render()
        n = len(self.search_state.matches)
        self.find_status.config(text=f"{self.search_state.index + 1}/{n}")

    def _find_next(self, event=None):
        if self.doc is None:
            return
        if self.find_var.get() != self.search_state.query or not self.search_state.matches:
            if self._run_find() == 0:
                return
        else:
            self.search_state.advance()
        self._jump_to_current_match()

    def _find_prev(self, event=None):
        if self.doc is None:
            return
        if self.find_var.get() != self.search_state.query or not self.search_state.matches:
            if self._run_find() == 0:
                return
        else:
            self.search_state.retreat()
        self._jump_to_current_match()

    def _toggle_toc_panel(self):
        settings.save({"toc_visible": self.toc_visible.get()})
        if self.toc_visible.get():
            # before=self._canvas_frame guarantees the TOC lands as the
            # LEFT pane every time it's re-shown -- PanedWindow.add()
            # would otherwise always append to the end (the right
            # side, past the already-present canvas pane) on a second
            # show. self._canvas_frame (not self.canvas) is the real
            # pane widget since the h/v scrollbar wiring wrapped the
            # canvas in a frame together with its scrollbars.
            self._content_frame.add(self.toc_frame, before=self._canvas_frame, width=240, minsize=100)
        else:
            self._content_frame.forget(self.toc_frame)

    def _refresh_outline(self):
        self.toc_tree.delete(*self.toc_tree.get_children())
        outline = self.viewer.get_outline()
        if not outline:
            self.toc_tree.insert("", "end", text="(no table of contents)")
            return
        # stack of (level, item_id) to attach children under the right parent
        stack = []
        for level, title, page_num in outline:
            item = self.toc_tree.insert(
                "", "end", text=title, values=(page_num,), open=True
            )
            stack = [s for s in stack if s[0] < level]
            parent = stack[-1][1] if stack else ""
            if parent:
                self.toc_tree.move(item, parent, "end")
            stack.append((level, item))

    def _on_toc_select(self, event=None):
        sel = self.toc_tree.selection()
        if not sel:
            return
        values = self.toc_tree.item(sel[0], "values")
        if not values:
            return
        self._go_to_page(int(values[0]))

    # ------------------------------------------------------------------
    # opening / closing documents
    # ------------------------------------------------------------------
    def _save_open_tabs(self):
        """Called after every tab open/close, not just on window-close,
        so a crash or a hard kill still leaves an accurate session to
        restore. Also called on every page turn (_go_to_page) so the
        saved position is never stale -- open/close alone would only
        capture whatever page a tab happened to be on at the LAST
        add/remove, not wherever it was actually left. t.viewer is the
        real, live Viewer object for that tab (Tab.__init__ keeps it),
        the same object self.viewer points at while that tab is active
        -- so t.viewer.page_num is always current, no extra sync needed
        even for background tabs."""
        settings.save({
            "open_tabs": [{"path": t.path, "page": t.viewer.page_num} for t in self._tabs]
        })

    def _open_document(self, path):
        abspath = os.path.abspath(path)
        for i, existing in enumerate(self._tabs):
            if os.path.abspath(existing.path) == abspath:
                self._select_tab(self._tab_frames[i])  # already open -- just switch to it
                return

        open_path = path
        if path.lower().endswith(".epub"):
            try:
                open_path = epubfix.fix_epub_encoding_conflicts(path)
            except Exception:
                open_path = path  # fail soft -- open the original rather than block on this
            doc = fitz.open(open_path)
        elif path.lower().endswith((".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff")):
            # fitz/PyMuPDF can't render HTML+CSS+JS at all, and treats
            # a bare image as a 1-page doc without the same page-image
            # pipeline the rest of Slate expects -- convert.path_to_pdf
            # routes both through a real PDF first. Fail LOUD here
            # (unlike epub's fail-soft): an HTML/image open with no
            # working conversion has no sane fallback the way epub's
            # original-file-with-a-decoding-quirk does.
            open_path = convert.path_to_pdf(path)
            doc = fitz.open(open_path)
        elif path.lower().endswith(CODE_TEXT_EXTENSIONS):
            doc = fitz.open(open_path, filetype="txt")
        else:
            doc = fitz.open(open_path)
        # Tab keeps the ORIGINAL path (tab label/title/recent-files all
        # show the real filename) even when doc was actually opened
        # from a corrected temp copy.
        new_viewer = Viewer(doc)
        # A user-chosen zoom carries across documents/launches instead
        # of every new document silently reverting to
        # Viewer.DEFAULT_ZOOM. None means "never explicitly set yet" --
        # leaves the class's own default alone in that case.
        if self._saved_zoom is not None:
            new_viewer.zoom = self._saved_zoom
        new_tab = tabmodule.Tab(path, doc, new_viewer)
        self._tabs.append(new_tab)

        self._ensure_doc_view_widgets()
        if self.home_frame is not None:
            self.home_frame.destroy()
            self.home_frame = None
        self.body_frame.pack(fill=tk.BOTH, expand=True)

        placeholder = tk.Frame(self.tab_strip)  # never shown -- a pure tab-strip entry
        self.tab_strip.add(placeholder, text=f"{os.path.basename(path)}  {_TAB_CLOSE_GLYPH}")
        self._tab_frames.append(placeholder)
        self._select_tab(placeholder)

        recent.add_recent(path)
        self._save_open_tabs()

    def _select_tab(self, frame):
        """Selecting a Notebook tab only fires <<NotebookTabChanged>> on
        the next idle-loop pass, not synchronously -- without calling
        the handler directly here, app.doc would still be None right
        after _open_document() returned. The bound virtual event (real
        interactive tab clicks) still also fires afterward, which just
        reloads the same already-active tab -- idempotent, harmless."""
        self.tab_strip.select(frame)
        self._on_tab_strip_changed()

    def _on_tab_strip_changed(self, event=None):
        if self._active_tab is not None:
            # path/doc/viewer are fixed for a Tab's whole lifetime (only
            # ever set once, at creation, above) -- only these four can
            # have changed while this tab was active, so only these need
            # saving back before switching away.
            self._active_tab.mode = self.mode
            self._active_tab.page = self.page
            self._active_tab.pending_redactions = self._pending_redactions
            self._active_tab.search_state = self.search_state

        selected = self.tab_strip.select()
        if not selected:
            return
        tab = self._tabs[self.tab_strip.index(selected)]
        self._active_tab = tab

        self.path = tab.path
        self.doc = tab.doc
        self.viewer = tab.viewer
        self.page = tab.page
        self._pending_redactions = tab.pending_redactions
        self.search_state = tab.search_state
        self._set_mode(tab.mode)

        self.find_var.set(self.search_state.query)
        if self.search_state.matches:
            n = len(self.search_state.matches)
            self.find_status.config(
                text=f"{self.search_state.index + 1}/{n}" if self.search_state.index >= 0 else "no matches"
            )
        else:
            self.find_status.config(text="")

        self.root.title(self._title())
        self._refresh_outline()
        self.render()
        self._update_pdf_only_menu_state()

    def _update_pdf_only_menu_state(self):
        disable = self.doc is not None and not self.doc.is_pdf
        state = "disabled" if disable else "normal"
        for label in _FILE_PDF_ONLY_LABELS:
            self.filem.entryconfig(label, state=state)
        for label in _EDIT_PDF_ONLY_LABELS:
            self.editm.entryconfig(label, state=state)

    def do_close(self):
        if self._active_tab is None:
            return
        self._close_tab_by_index(self.tab_strip.index(self.tab_strip.select()))

    def _kb_next_tab(self, event=None):
        self._cycle_tab(1)

    def _kb_prev_tab(self, event=None):
        self._cycle_tab(-1)

    def _cycle_tab(self, direction):
        """Ctrl+Tab/Ctrl+Shift+Tab. Wraps around at either end, same
        convention as browser tabs."""
        tabs = self.tab_strip.tabs()
        if len(tabs) < 2:
            return
        current = self.tab_strip.index(self.tab_strip.select())
        self.tab_strip.select(tabs[(current + direction) % len(tabs)])

    def _on_tab_strip_click(self, event):
        """Middle-click closes a tab (same convention as Chrome/Firefox).
        ttk.Notebook.bbox() returns (0,0,0,0) for every tab (confirmed
        across 'default'/'clam'/Windows 'vista' themes) despite the
        widget being mapped with real, non-zero dimensions -- breaking
        any "click within N px of the tab's right edge" hit-test via the
        normal API. identify()/index() at a coordinate DO work
        correctly, so the close action is anchored to those instead.
        See _on_tab_strip_left_click for how the visible "x" glyph gets
        a real left-click hit-test too, working around the same bbox()
        gap a different way."""
        try:
            index = self.tab_strip.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        self._close_tab_by_index(index)

    def _on_tab_strip_left_click(self, event):
        """Left-click ON THE VISIBLE "x" glyph closes its tab. The "x"
        glyph was a visual hint only -- plain left-click has no
        built-in close behavior at all (only middle-click did, see
        _on_tab_strip_click), so clicking the thing that LOOKS
        clickable just reselected the tab.

        Can't fix this with a pixel-offset hit-test the obvious way --
        ttk.Notebook.bbox() is confirmed broken (see
        _on_tab_strip_click's docstring), so there's no reliable "this
        tab starts at x=N" to measure a close-zone against. Workaround:
        tab_strip.index(f"@{x},{y}") DOES resolve correctly at any
        coordinate even though bbox() lies -- scanning it forward one
        pixel at a time from the click point finds the real edge of the
        clicked tab, either where the index changes to the NEXT tab, or
        (critically, for the LAST tab) where querying past the last
        tab's real content raises a clean TclError instead of silently
        returning a wrong answer. Treats hitting the strip's own right
        edge (winfo_width()) as also in-bounds, matching a genuinely
        borderless case."""
        try:
            index = self.tab_strip.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return  # not on any tab -- let default handling (nothing) proceed
        strip_width = self.tab_strip.winfo_width()
        right_edge = event.x
        while right_edge < strip_width:
            try:
                idx_here = self.tab_strip.index(f"@{right_edge},{event.y}")
            except tk.TclError:
                break  # ran off the end of the last tab's real content
            if idx_here != index:
                break  # crossed into the next tab
            right_edge += 1
        close_zone_px = 18  # wide enough to comfortably cover "<label> x" plus a little slop
        if strip_width - right_edge < 2 or right_edge - event.x <= close_zone_px:
            self._close_tab_by_index(index)
            return "break"  # tab's being destroyed -- skip the default reselect

    def _close_tab_by_index(self, index):
        closing_tab = self._tabs.pop(index)
        closing_frame = self._tab_frames.pop(index)
        was_active = closing_tab is self._active_tab
        closing_tab.doc.close()
        self.tab_strip.forget(closing_frame)
        closing_frame.destroy()
        self._save_open_tabs()

        if not was_active:
            return  # closed a background tab -- nothing currently displayed changes

        if self._tabs:
            new_index = min(index, len(self._tabs) - 1)
            self._select_tab(self._tab_frames[new_index])
        else:
            self._active_tab = None
            self.path = None
            self.doc = None
            self.viewer = None
            self.page = None
            self._pending_redactions = []
            self.search_state = search.SearchState()
            self._set_mode("view")
            self.body_frame.pack_forget()
            self._show_home_screen()
            self._update_pdf_only_menu_state()

    # ------------------------------------------------------------------
    # viewer
    # ------------------------------------------------------------------
    def render(self):
        # Keep a persistent reference to the current page. fitz.Annot /
        # fitz.Widget objects hold only a WEAK reference to their parent
        # page (same gotcha as forms.py/DESIGN.md, hit again live here):
        # re-fetching self.doc[page_num] fresh inside every handler let
        # the previous page wrapper get garbage-collected, and a
        # just-added annotation would then raise "annotation not bound
        # to any page" the next time anything touched it. self.page is
        # the fix -- always use it, never re-index self.doc directly.
        self.page = self.doc[self.viewer.page_num]
        # Genuinely branch rather than thread view_mode ifs through one
        # render path -- search-highlight/selection overlays both need
        # "+ page offset" in continuous mode, so unifying the two paths
        # would mean offset-plumbing every call site anyway.
        self._suppress_scroll_sync = True
        try:
            if self.continuous_scroll:
                self._render_continuous()
            else:
                self._render_static_row()
        finally:
            self._suppress_scroll_sync = False
        pending_here = sum(1 for p, _ in self._pending_redactions if p == self.viewer.page_num)
        # Page number moved to the centered Foxit-style box -- status
        # now carries only zoom/pending-redaction.
        self.status.config(
            text=f"zoom {self.viewer.zoom:.2f}x"
            + (f"  ({pending_here} pending redaction)" if pending_here else "")
        )
        self.page_entry_var.set(str(self.viewer.page_num + 1))
        self.page_total_label.config(text=f"of {self.viewer.page_count}")
        if hasattr(self, "columns_entry_var"):
            self.columns_entry_var.set(str(self.num_columns))

    def _colorize_for_theme(self, img):
        # A raw invert only reads right for the plain built-in "dark"
        # theme -- it leaves every LIGHT-toned named theme's page pure
        # white, not tinted to that theme's own paper color, so the
        # reading surface doesn't match the chrome at all.
        # ImageOps.colorize maps the page's own light->dark tones onto
        # the theme's canvas_bg->fg pair instead of a flat invert -- one
        # mechanism for every theme, light or dark alike (for the plain
        # "light" theme this is a near no-op, black->black and
        # white->near-white). Photos/images on the page recolor too,
        # same accepted simple tradeoff as Sumatra's own basic
        # color-inversion feature, just via a nicer mapping.
        #
        # Opt-in, not opt-out: that tradeoff actively destroys content
        # where color IS the payload -- a categorical-color-coded
        # diagram's legend goes meaningless once flattened to one tint.
        # self.colorize_pages defaults False -- checking "Colorize pages
        # to theme" in the View menu is how a prose-only reader opts
        # into the tinted-to-theme look.
        if not self.colorize_pages:
            return img
        colors = theme.get_palette(self.theme_name.get())
        return ImageOps.colorize(img.convert("L"), black=colors["fg"], white=colors["canvas_bg"])

    def _render_static_row(self):
        """The "not scrolling" axis -- side-by-side is an independent
        checkbox, not a third radio option, so this replaces the old
        single-page-only
        _render_single with a cols-aware version: cols=1 is byte-
        identical to the original (one page, canvas sized exactly to
        it, no scrollbar needed); cols=2 is a static two-page spread,
        same shape. Always builds self._layout (even though only this
        row's 1-2 pages ever get drawn) so every coordinate-resolution
        call site can generalize to "does self._layout exist" instead
        of a mode check -- cheap at this scale, no windowing/cache
        pressure the way continuous mode needs.

        self._layout.rect_of() gives each page's TRUE position in the
        full document stack (what continuous mode needs) -- for a page
        deep in a long document that's nowhere near canvas origin, so
        this translates the row to (0, 0) via self._static_row_offset,
        which _page_offset() applies symmetrically when resolving a
        click back to PDF space."""
        cols = self.num_columns
        zoom = self.viewer.zoom
        crop_rect = self._get_crop_rect()
        need_new_layout = (
            self._layout is None or self._layout_doc is not self.doc
            or self._layout.zoom != zoom or self._layout.cols != cols
            or self._layout.crop_rect != crop_rect
        )
        if need_new_layout:
            self._layout = layout.PageLayout(self.doc, zoom, cols=cols, crop_rect=crop_rect)
            self._layout_doc = self.doc
            self._page_cache.invalidate_all()
            self._last_window = set()
        row_start = (self.viewer.page_num // cols) * cols
        row_pages = list(range(row_start, min(row_start + cols, self.viewer.page_count)))
        row_y0 = self._layout.rect_of(row_pages[0])[1]
        self._static_row_offset = (0, row_y0)
        self._page_cache.set_window(set(row_pages))  # only this row's images stay cached
        self._last_window = set(row_pages)
        self.canvas.delete("all")
        self._page_canvas_items = {}
        self._page_placeholder_items = {}
        self._selection_highlight_photos = []  # once per render pass -- see _draw_text_selection_for_page
        self._search_highlight_photos = []  # once per render pass -- see _draw_search_highlights_for_page
        max_x1 = max_y1 = 0.0
        for page_num in row_pages:
            x0, y0, _x1, _y1 = self._layout.rect_of(page_num)
            self._draw_real_page(page_num, x0, y0 - row_y0)
            # Real ACTUAL rendered pixel dimensions (PhotoImage.width()/
            # height()), not the layout's pure page_rect*zoom float math
            # -- PyMuPDF's rasterizer rounds to a whole pixel count
            # (e.g. 595pt * 1.5 = 892.5 -> a real 893px image), so using
            # the float would size the canvas/scrollregion half a pixel
            # too small, a real (if tiny) edge-clipping regression
            # caught by test_scrollregion_is_set_to_the_rendered_page_size.
            tkimg = self._page_cache.get(page_num)
            max_x1 = max(max_x1, x0 + tkimg.width())
            max_y1 = max(max_y1, (y0 - row_y0) + tkimg.height())
        self.canvas.config(width=max_x1, height=max_y1)
        self.canvas.config(scrollregion=(0, 0, max_x1, max_y1))
        # Force geometry to settle now -- callers that inspect
        # canvas.yview() right after render() (rubber-band wheel logic,
        # _wheel_fits_viewport) need a real reading immediately, not
        # Tk's stale (0.0, 0.0) "not yet computed" sentinel.
        self.canvas.update_idletasks()

    def _get_crop_rect(self):
        """Cached per-DOCUMENT, not recomputed every render -- sampling
        several pages' real text/image/drawing bboxes (detect_content_bbox)
        isn't free, and the result can't change unless the document
        itself does. Returns None when crop_to_content is off, or when
        detection found nothing safe to crop to (a real, non-error case
        -- see detect_content_bbox's own docstring); callers already
        treat None as "render/layout the full page, unchanged"."""
        if not self.crop_to_content:
            return None
        if self._crop_rect_doc is not self.doc:
            self._crop_rect = detect_content_bbox(self.doc)
            self._crop_rect_doc = self.doc
        return self._crop_rect

    def _make_page_image(self, page_num):
        """PageImageCache's fill function -- only called on a real
        cache miss (a page entering the window for the first time)."""
        img = self._colorize_for_theme(
            self.viewer.render_page(page_num=page_num, clip=self._get_crop_rect())
        )
        return ImageTk.PhotoImage(img)

    def _viewport_height(self) -> float:
        h = self.canvas.winfo_height()
        # Not yet geometry-realized (e.g. very first render): a
        # reasonable fallback so the window isn't computed with zero
        # slack -- corrected automatically on the next real render/scroll.
        return h if h > 1 else 600

    def _compute_window(self) -> list:
        """Real page range worth keeping rendered: viewport ± one
        screenful of slack -- self-adjusts to zoom/viewport size, no
        tuned page-count constant.

        Trusts canvas.yview() -- only valid once the scrollregion
        reflects the CURRENT layout. Calling this before a render pass
        updates the scrollregion reads a STALE fraction (from whatever
        the previous, differently-sized mode/layout had) against the
        NEW total_h, producing a nonsensical window that could span
        nearly the whole document. _render_continuous's first-ever build for
        a given layout uses _window_around_page instead, anchored to
        the page we already know should be visible rather than a
        scroll fraction that might not correspond to this layout at
        all; this method is for _shift_window's organic-scroll case,
        where the scrollregion is already correctly set from a prior
        render."""
        if self._layout is None:
            return []
        first, last = self.canvas.yview()
        _total_w, total_h = self._layout.total_size
        viewport_h = self._viewport_height()
        top_y = first * total_h - viewport_h
        bottom_y = last * total_h + viewport_h
        return self._layout.pages_in_range(top_y, bottom_y)

    def _window_around_page(self, page_num) -> list:
        """Page range anchored to a KNOWN page (viewport ± one
        screenful of slack), not to canvas.yview() -- used for a fresh
        layout build, where any scroll fraction read before this same
        render pass sets the new scrollregion would be stale (see
        _compute_window's docstring)."""
        if self._layout is None:
            return []
        _x0, y0, _x1, y1 = self._layout.rect_of(page_num)
        viewport_h = self._viewport_height()
        return self._layout.pages_in_range(y0 - viewport_h, y1 + viewport_h)

    def _draw_real_page(self, page_num, x0, y0):
        tkimg = self._page_cache.get(page_num)
        item = self.canvas.create_image(int(x0), int(y0), anchor=tk.NW, image=tkimg)
        self._page_canvas_items[page_num] = item
        self._draw_search_highlights_for_page(page_num, x0, y0)
        self._draw_text_selection_for_page(page_num, x0, y0)

    def _draw_placeholder(self, page_num, x0, y0, x1, y1, colors):
        item = self.canvas.create_rectangle(x0, y0, x1, y1, fill=colors["canvas_bg"], outline="")
        self._page_placeholder_items[page_num] = item

    def _render_continuous(self):
        """Windowed rendering: an eager render-every-page-on-every-
        render()-call approach re-rasterizes the WHOLE document on every
        navigation/zoom/theme change, which locks up on PageUp/PageDown
        for any nontrivial document. Only pages near the viewport (± one
        screenful of slack) get a real PhotoImage; everything else is a
        cheap colored placeholder rect, lazily upgraded as the window
        moves (see _shift_window, the pure-scroll incremental path that
        avoids even this full rebuild for ordinary scrolling)."""
        cols = self.num_columns
        zoom = self.viewer.zoom
        # Centering: continuous mode deliberately does NOT resize the
        # canvas WIDGET to content (see the scrollregion comment below),
        # so on any window wider than the document, content was pinned to
        # the left edge with a dead gap on the right. update_idletasks() +
        # winfo_width() > 1 guard is the same established pattern
        # _apply_width_based_side_by_side/fit_width already use for a
        # reliable width read. Zero when content is already >= viewport
        # (nothing to center -- that's the real horizontal-scroll case,
        # left-pinned is correct there, unchanged from before this fix).
        # content_width comes from a cheap throwaway PageLayout (pure page-
        # dimension math, no rendering) rather than reusing self._layout,
        # so a repeated render at an unchanged viewport never measures its
        # OWN previous offset and compounds it.
        crop_rect = self._get_crop_rect()
        # update_idletasks() before winfo_width() is required here, not
        # optional: without a forced idle-tasks flush, winfo_width() can
        # return a stale cached width right after a column count change
        # (Settings' -/+ buttons fire synchronously, before Tk's own
        # event loop has processed the geometry change that triggered
        # this render), producing a wrong content_w/center_offset_x and,
        # in the worst case, a layout computed against a pre-resize
        # viewport that doesn't match what actually gets drawn -- a race,
        # not a hard failure, so it doesn't reproduce every time.
        self.canvas.update_idletasks()
        viewport_w = self.canvas.winfo_width()
        content_w = layout.PageLayout(self.doc, zoom, cols=cols, crop_rect=crop_rect).content_width
        center_offset_x = max(0.0, (viewport_w - content_w) / 2) if viewport_w > 1 else 0.0
        need_new_layout = (
            self._layout is None or self._layout_doc is not self.doc
            or self._layout.zoom != zoom or self._layout.cols != cols
            or self._layout.center_offset_x != center_offset_x
            or self._layout.crop_rect != crop_rect
        )
        if need_new_layout:
            self._layout = layout.PageLayout(
                self.doc, zoom, cols=cols, center_offset_x=center_offset_x, crop_rect=crop_rect
            )
            self._layout_doc = self.doc
            self._page_cache.invalidate_all()
            self._last_window = set()
        # Continuous mode always draws pages at their TRUE absolute
        # position -- no row-relative translation the way static mode
        # needs (_render_static_row), so this always stays (0, 0) here.
        self._static_row_offset = (0, 0)
        self.canvas.delete("all")
        self._page_canvas_items = {}
        self._page_placeholder_items = {}
        self._selection_highlight_photos = []  # once per render pass -- see _draw_text_selection_for_page
        self._search_highlight_photos = []  # once per render pass -- see _draw_search_highlights_for_page
        # Anchored to viewer.page_num (the page we KNOW should be
        # visible), not canvas.yview() -- the scrollregion for THIS
        # layout hasn't been set yet at this point in the call, so any
        # scroll fraction read here would be stale (see
        # _compute_window's docstring for the real bug this avoids).
        window = set(self._window_around_page(self.viewer.page_num))
        self._page_cache.set_window(window)
        self._last_window = window
        colors = theme.get_palette(self.theme_name.get())
        rects = self._layout.all_rects()
        for idx, (page_num, x0, y0, x1, y1) in enumerate(rects):
            if page_num in window:
                self._draw_real_page(page_num, x0, y0)
            else:
                self._draw_placeholder(page_num, x0, y0, x1, y1, colors)
            # A page that ends with a lot of its own trailing whitespace
            # (baked into that page's real content, not something Slate
            # can crop without risking real content) reads as an
            # unexplained blank void without this -- a subtle line at
            # the real page boundary marks it as an intentional break.
            # Row-boundary only (Slice 4: side-by-side means more than
            # one page can share a row) -- drawn once per row, at the
            # last (rightmost) page's own bottom edge, spanning the
            # full row width rather than just that one page's column.
            is_last_in_row = (idx + 1) % self._layout.cols == 0
            if is_last_in_row and idx < len(rects) - 1:
                row_w, _total_h = self._layout.total_size
                line_y = y1 + self._layout.gap / 2
                # Starts at center_offset_x, not 0 -- with centering
                # active, x=0 is empty left margin, not the real page
                # edge; the line would otherwise bleed through that dead
                # space instead of tracking the actual content.
                self.canvas.create_line(
                    self._layout.center_offset_x, line_y, row_w, line_y,
                    fill=colors["muted_fg"], width=1,
                )
        total_w, total_h = self._layout.total_size
        # Deliberately NOT canvas.config(width=, height=) here (unlike
        # _render_single, where the canvas SHOULD size to exactly one
        # page) -- sizing the canvas WIDGET itself to the full stacked
        # document height means that, on a fresh window with no prior
        # smaller render to anchor a sane size, Tk lets the TOPLEVEL grow
        # to fit that huge request outright (nothing exists yet to clip
        # it against), so canvas.yview() reports "everything fits" even
        # for a document far taller than any real screen. scrollregion
        # alone is correct here -- the
        # canvas's on-screen size should stay whatever the container
        # actually gives it; that's the entire point of a scrollable
        # viewport onto a larger virtual content area.
        self.canvas.config(scrollregion=(0, 0, total_w, total_h))
        self.canvas.update_idletasks()

    def _shift_window(self):
        """Pure-scroll incremental update -- no canvas.delete('all'),
        only the window boundary's own diff touches the canvas. Hooked
        from _sync_page_num_from_scroll (already fires from every real
        scroll trigger: wheel, scrollbar drag, yscrollcommand) so
        ordinary scrolling never pays a full-rebuild cost regardless of
        document length."""
        if not self.continuous_scroll or self._layout is None:
            return
        new_window = set(self._compute_window())
        if new_window == self._last_window:
            return
        colors = theme.get_palette(self.theme_name.get())
        for page_num in self._last_window - new_window:
            item = self._page_canvas_items.pop(page_num, None)
            if item is not None:
                self.canvas.delete(item)
            x0, y0, x1, y1 = self._layout.rect_of(page_num)
            self._draw_placeholder(page_num, x0, y0, x1, y1, colors)
        for page_num in new_window - self._last_window:
            ph_item = self._page_placeholder_items.pop(page_num, None)
            if ph_item is not None:
                self.canvas.delete(ph_item)
            x0, y0, _x1, _y1 = self._layout.rect_of(page_num)
            self._draw_real_page(page_num, x0, y0)
        self._page_cache.set_window(new_window)
        self._last_window = new_window

    def _draw_search_highlights_for_page(self, page_num, ox, oy):
        """Canvas-only overlay, not real annotations -- cleared and
        redrawn every render() same as the page image itself. ox/oy is
        the page's canvas-space origin -- always (0, 0) in single-page
        mode, so this is byte-identical to the pre-Slice-2 math there.

        Outline was hardcoded plain "yellow"/"red", ignoring the active
        theme entirely -- true in every theme, not just Bonepaper. A thin
        theme-colored OUTLINE rectangle (select_bg for ordinary matches,
        accent2 for the current one) isn't enough visual weight for
        something meant to draw the eye, no matter the hue. Built instead
        as a real filled translucent overlay, same technique
        _draw_text_selection_for_page already uses (RGBA
        PhotoImage, not a stippled/outlined canvas primitive) -- ordinary
        matches at the same ~35% opacity live selection uses, the
        CURRENT match bumped to ~55% opacity PLUS a solid accent2 border
        on top, so it reads as unambiguously "this one" even sitting
        right next to other matches on the same page."""
        if not self.search_state.matches:
            return
        colors = theme.get_palette(self.theme_name.get())
        z = self.viewer.zoom
        current = self.search_state.current()

        def _rgb(hexval):
            h = hexval.lstrip("#")
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

        select_rgb = _rgb(colors["select_bg"])
        accent2_rgb = _rgb(colors["accent2"])
        for rect in self.search_state.matches_on_page(page_num):
            is_current = current is not None and current[0] == page_num and current[1] == rect
            px0, py0 = ox + rect.x0 * z, oy + rect.y0 * z
            px1, py1 = ox + rect.x1 * z, oy + rect.y1 * z
            pw, ph = max(1, round(px1 - px0)), max(1, round(py1 - py0))
            rgb = accent2_rgb if is_current else select_rgb
            alpha = 140 if is_current else 90  # ~55% current, ~35% others (matches selection's own opacity)
            overlay = Image.new("RGBA", (pw, ph), rgb + (alpha,))
            photo = ImageTk.PhotoImage(overlay)
            self._search_highlight_photos.append(photo)  # keep ref, Tk drops GC'd images
            self.canvas.create_image(px0, py0, anchor="nw", image=photo, tags=("search_highlight",))
            if is_current:
                self.canvas.create_rectangle(
                    px0, py0, px1, py1, outline=colors["accent2"], width=2,
                )

    def _draw_text_selection_for_page(self, page_num, ox, oy):
        """Canvas-only overlay, same convention as
        _draw_search_highlights_for_page -- cleared and redrawn every
        render() alongside the page image, never a real annotation.
        Uses the active theme's highlight_bg (was a hardcoded blue
        "#3a5a7a" regardless of theme) -- for inkbone this is the one
        place green survives as a real, minimal, pure accent, not
        select_bg (tabs, now monochrome). A selection holds (page_num,
        word) pairs -- each page draws only its own words, filtered out
        of the whole selection here, so a selection spanning several
        pages still renders correctly, once per resident page.

        A real highlighter bar, not one stippled rectangle PER SELECTED
        WORD, which read as a scattered multicursor-style pattern (gaps
        between words, a dithered fill). Same two
        root causes as _update_tts_highlight's docstring (that fix is
        the reference pattern this one follows, code not shared since
        the TTS path stays untouched): per-word boxes instead of one
        box per LINE, and `stipple` faking transparency by literally
        not painting ~50% of pixels rather than real alpha-blending. Fixed
        the same way -- group words by PyMuPDF's (block_no, line_no)
        into one continuous rectangle per line, spanning min(x0)..
        max(x1) for that line, and paint it as a real translucent RGBA
        PhotoImage instead of a stippled canvas fill.

        A selection can span many lines (unlike the single-window TTS
        highlight), so this keeps a LIST of PhotoImage references in
        self._selection_highlight_photos (Tk drops a PhotoImage's pixels
        blank once nothing references it, even though the canvas item
        persists). The list is reset ONCE per render pass, at the top
        of _render_continuous/_render_static_row (alongside their own
        canvas.delete("all")) -- NOT here.

        This function runs once per VISIBLE page (_draw_real_page is
        called for every resident page in the window, and continuous
        mode routinely has 2+ pages resident), so resetting
        self._selection_highlight_photos = [] on EVERY non-matching
        page's early return would wipe the correct page's images right
        after they're drawn, whenever a non-matching page is processed
        later in the SAME render pass. This function only ever APPENDS
        its own page's images to the list (the caller resets it once
        for the whole pass); a non-matching page does a bare return,
        touching nothing."""
        page_words = [w for pn, w in self._selected_words if pn == page_num]
        if not page_words:
            return
        colors = theme.get_palette(self.theme_name.get())
        z = self.viewer.zoom
        hexc = colors["highlight_bg"].lstrip("#")
        r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
        lines = {}
        for word in page_words:
            lines.setdefault((word[5], word[6]), []).append(word)
        for line_words in lines.values():
            lx0 = min(word[0] for word in line_words)
            ly0 = min(word[1] for word in line_words)
            lx1 = max(word[2] for word in line_words)
            ly1 = max(word[3] for word in line_words)
            px0, py0 = ox + lx0 * z, oy + ly0 * z
            px1, py1 = ox + lx1 * z, oy + ly1 * z
            pw, ph = max(1, round(px1 - px0)), max(1, round(py1 - py0))
            overlay = Image.new("RGBA", (pw, ph), (r, g, b, 90))  # ~35% opacity
            photo = ImageTk.PhotoImage(overlay)
            self._selection_highlight_photos.append(photo)  # keep ref, Tk drops GC'd images
            self.canvas.create_image(px0, py0, anchor="nw", image=photo, tags=("text_selection",))

    def _selected_text(self) -> str:
        # self._selected_words is (page_num, word) pairs, already built
        # in page/reading order (see _on_drag) -- just pull the text
        # field back out.
        return " ".join(w[4] for _pn, w in self._selected_words)

    def _copy_selection(self, event=None):
        text = self._selected_text()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _selection_line_rects(self):
        """Group self._selected_words into one (page_num, fitz.Rect) per
        line -- same (block_no, line_no) grouping
        _draw_text_selection_for_page already uses for the highlight
        overlay, reused here so "Highlight Selection"/"Redact Selection"
        mark exactly what the on-screen highlight visually shows, page
        by page across a cross-page selection."""
        groups = {}
        for page_num, w in self._selected_words:
            groups.setdefault((page_num, w[5], w[6]), []).append(w)
        rects = []
        for (page_num, _block_no, _line_no), words in groups.items():
            x0 = min(w[0] for w in words)
            y0 = min(w[1] for w in words)
            x1 = max(w[2] for w in words)
            y1 = max(w[3] for w in words)
            rects.append((page_num, fitz.Rect(x0, y0, x1, y1)))
        return rects

    def _highlight_selection(self):
        # Pass the active theme's real highlight_bg at the same ~35%
        # opacity the live selection overlay already uses
        # (_draw_text_selection_for_page) so a saved highlight looks
        # like what was on screen before saving it.
        colors = theme.get_palette(self.theme_name.get())
        hexc = colors["highlight_bg"].lstrip("#")
        rgb = tuple(int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
        for page_num, rect in self._selection_line_rects():
            annotate.add_highlight(self.doc[page_num], rect, color=rgb, opacity=0.35)
        self._selected_words = []
        self.render()

    def _redact_selection(self):
        for page_num, rect in self._selection_line_rects():
            self._pending_redactions.append((page_num, rect))
        self._selected_words = []
        self.render()

    def _show_canvas_context_menu(self, event):
        """Right-click on the document canvas, view mode only (redact/
        annotate/forms/textedit have their own drag gestures -- an
        unrelated context menu popping mid-gesture there would be
        surprising, not helpful). The standard PDF-reader menu set this
        app can actually back with a real feature: Copy/Highlight/Redact
        (enabled only when there's a live selection), Read from here
        (today's earlier feature, moved from an instant right-click
        action into this menu), Zoom, and first/last page. Nothing here
        is a new capability -- every item calls something that already
        exists elsewhere in the app; this is one discoverable place to
        reach it without hunting menus."""
        if self.mode != "view":
            return
        has_selection = bool(self._selected_words)
        sel_state = "normal" if has_selection else "disabled"
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Copy", command=self._copy_selection, state=sel_state)
        menu.add_command(label="Highlight Selection", command=self._highlight_selection, state=sel_state)
        menu.add_command(label="Redact Selection", command=self._redact_selection, state=sel_state)
        menu.add_separator()
        # Captures THIS click's own event (coordinates), not whichever
        # point the mouse happens to be at when the menu item is later
        # chosen -- the menu can stay open a while before a real click.
        menu.add_command(label="Read from here", command=lambda: self._read_from_word_click(event))
        menu.add_separator()
        menu.add_command(label="Zoom In", command=self.zoom_in)
        menu.add_command(label="Zoom Out", command=self.zoom_out)
        menu.add_command(label="Fit Width", command=self.fit_width)
        menu.add_separator()
        menu.add_command(label="First Page", command=self._kb_first_page)
        menu.add_command(label="Last Page", command=self._kb_last_page)
        self._paint_widget(menu, theme.get_palette(self.theme_name.get()))
        menu.tk_popup(event.x_root, event.y_root)

    def next(self):
        """Toolbar/page-box arrows, Right/Down/PageDown/j -- all route
        here. Continuous mode (Slice 2): _go_to_page scrolls to the
        target page's real position instead of jumping back to canvas
        origin (_reset_scroll would land on page 1's top regardless of
        which page was current -- a real bug this fixes, not a style
        choice). Side by side (Slice 4): steps by a whole spread (2
        pages), not 1, same as Adobe/Foxit's own two-page-view nav."""
        if self.viewer is None:
            return
        if self.viewer.page_num >= self.viewer.page_count - 1:
            return
        step = self.num_columns
        self._go_to_page(min(self.viewer.page_num + step, self.viewer.page_count - 1))

    def prev(self):
        """See next()'s docstring."""
        if self.viewer is None:
            return
        if self.viewer.page_num <= 0:
            return
        step = self.num_columns
        self._go_to_page(max(self.viewer.page_num - step, 0))

    def _prev_page_landing_at_bottom(self):
        """Same as prev(), except a wheel-driven page-turn arrives from
        BELOW (scrolling up past the top edge) and should land at the
        new page's bottom, not its top -- asymmetric from every other
        prev-page trigger (keyboard/j/PageUp/TOC-select all keep
        landing top-left via prev()+_reset_scroll(), unchanged)."""
        if self.viewer is None:
            return
        self.viewer.prev_page()
        self._selected_words = []
        self.render()
        self.canvas.yview_moveto(1.0)

    def _wheel_fits_viewport(self) -> bool:
        """True if the current page's scrollregion is already fully
        visible (canvas.yview() returns the visible fraction range) --
        the same test collapses rubber-band wheel to today's exact
        unconditional-page-turn behavior whenever nothing has changed
        (no zoom past viewport), so no regression for the common case."""
        first, last = self.canvas.yview()
        return (last - first) >= 0.999

    def _wheel_up(self, event=None):
        """Rubber-band wheel: page-turn only when the page already fits
        the viewport OR the view is scrolled to the very top edge;
        otherwise real scroll. Direction-only -- X11 Button-4 and
        Windows/Mac MouseWheel(up) both call this, neither needs delta
        magnitude for this logic (previously the two platforms went
        through DIFFERENT code paths, which happened to agree only
        because both did the same unconditional thing).

        Continuous mode: page boundaries are a soft concept once every
        page is stacked in
        one scrollable canvas -- no edge-landing logic, just real
        scroll or a no-op at the very top. _wheel_fits_viewport()
        needs no change for this: it already means "does content
        overflow the viewport," not "does the page," so a short
        document that fits on screen still no-ops for free."""
        if self._typing_in_entry() or self.viewer is None:
            return
        if self.continuous_scroll:
            if not self._wheel_fits_viewport():
                self.canvas.yview_scroll(-1, "units")
                # yview_scroll's own yscrollcommand callback isn't a
                # reliable trigger in every environment (plain
                # yview_moveto()/scrollbar-drag doesn't fire it under a
                # headless Xvfb, even after root.update()) -- called
                # explicitly so the page-number
                # box can't silently freeze while wheel-scrolling.
                self._sync_page_num_from_scroll()
            return
        if self._wheel_fits_viewport():
            self.prev()
            return
        first, _last = self.canvas.yview()
        if first <= 0.0001:
            self._prev_page_landing_at_bottom()
        else:
            self.canvas.yview_scroll(-1, "units")

    def _wheel_down(self, event=None):
        """Rubber-band wheel, downward -- see _wheel_up's docstring."""
        if self._typing_in_entry() or self.viewer is None:
            return
        if self.continuous_scroll:
            if not self._wheel_fits_viewport():
                self.canvas.yview_scroll(1, "units")
                self._sync_page_num_from_scroll()  # see _wheel_up's comment
            return
        if self._wheel_fits_viewport():
            self.next()
            return
        _first, last = self.canvas.yview()
        if last >= 0.9999:
            self.next()  # lands at top via _reset_scroll(), same as every other next-page trigger
        else:
            self.canvas.yview_scroll(1, "units")

    def _on_mouse_wheel(self, event):
        """Windows/Mac only -- delivers a signed event.delta (Windows:
        +/-120 per notch); X11 has no <MouseWheel> event at all, wheel
        arrives as Button-4/Button-5 clicks instead (bound separately,
        routed through the same _wheel_up/_wheel_down dispatch)."""
        if event.delta > 0:
            self._wheel_up()
        else:
            self._wheel_down()

    def _on_ctrl_mouse_wheel(self, event):
        """Ctrl+scroll = zoom, same signed-delta convention as
        _on_mouse_wheel above."""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _on_shift_mouse_wheel(self, event):
        """Shift+scroll = horizontal scroll. Windows/Mac deliver a signed
        event.delta same as plain wheel; X11 has no
        <Shift-MouseWheel>, bound separately via Shift-Button-4/5 below."""
        if self._typing_in_entry() or self.viewer is None:
            return
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")

    def _shift_wheel_left(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self.canvas.xview_scroll(-1, "units")

    def _shift_wheel_right(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self.canvas.xview_scroll(1, "units")

    def zoom_in(self):
        self.viewer.zoom_in()
        self.render()
        settings.save({"zoom": self.viewer.zoom})

    def zoom_out(self):
        self.viewer.zoom_out()
        self.render()
        settings.save({"zoom": self.viewer.zoom})

    def fit_width(self):
        # Cancel any pending debounced _apply_width_based_side_by_side
        # (see _on_canvas_frame_configure) -- without this, a resize
        # shortly before this call can leave that 150ms timer still
        # armed; it fires AFTER this method returns, using stale
        # pre-fit geometry, and its own _render_current_layout() call
        # can re-render at a different column count than what was just
        # explicitly fitted, silently undoing it. Real bug: "clicking
        # Fit Width often doesn't render at the new size."
        if self._autolayout_after_id is not None:
            self.root.after_cancel(self._autolayout_after_id)
            self._autolayout_after_id = None
        # Manual command, not an auto-apply-on-open default: auto-fitting
        # on every open broke 131 existing tests that hardcode
        # DEFAULT_ZOOM as document-open's fixed, predictable starting
        # point (zoom_in/out deltas, cache-invalidation checks,
        # wheel-scroll page-fit math). Same update_idletasks() timing
        # fix still applies here (Tk's next idle-loop pass otherwise
        # reports a stale canvas width).
        #
        # Fitting ONE page's width to the FULL viewport ignores
        # side_by_side -- in Book View (2 columns) that zooms the page
        # spread to twice the width that actually fits, so only the left
        # page's left portion ever shows without horizontal scrolling.
        # Divide the viewport across however many columns are actually
        # showing (matching layout.PageLayout's own cols/gap math
        # exactly, not a separate guess at it) before fitting.
        self.canvas.update_idletasks()
        viewport_w = self.canvas.winfo_width()
        if viewport_w > 1:
            cols = self.num_columns
            gap = 2  # matches layout.PageLayout's own default gap= exactly
            per_page_w = (viewport_w - gap * (cols - 1)) / cols
            # Without this, Fit Width always measures the FULL native
            # page width even with crop on, so the margin space crop
            # frees up never gets handed back to the reader as extra
            # zoom -- see viewer.fit_width's own content_width comment
            # for the full story.
            crop_rect = self._get_crop_rect()
            content_width = crop_rect.width if crop_rect is not None else None
            self.viewer.fit_width(per_page_w, content_width=content_width)
            self.render()
            settings.save({"zoom": self.viewer.zoom})

    # ------------------------------------------------------------------
    # canvas interaction (redact / annotate / forms all live here)
    # ------------------------------------------------------------------
    def _page_offset(self, page_num):
        """(x0, y0) canvas-space origin of this page, exactly matching
        wherever it was actually drawn. Generalizes to "does
        self._layout exist" rather than a mode check -- self._layout
        exists in all four continuous_
        scroll/side_by_side combinations now. self._static_row_offset
        is (0, 0) in continuous mode (rect_of()'s true absolute
        position is exactly what was drawn there) and the current
        row's translation in static mode (_render_static_row draws the
        row at canvas origin, not its true, possibly-deep-in-the-
        document position) -- always (0, 0) in single-page/cols=1
        static mode too, byte-identical to the pre-Slice-2 math."""
        if self._layout is None:
            return 0, 0
        x0, y0, _x1, _y1 = self._layout.rect_of(page_num)
        ox, oy = self._static_row_offset
        return x0 - ox, y0 - oy

    def _word_index_near_point(self, words, x, y) -> int:
        """Index into `words` (PyMuPDF's get_text("words") list, already
        in natural reading order) of whichever word is under (x, y) in
        PDF space, or nearest it if the point falls in blank space
        between/around words (the common case -- most clicks don't
        land pixel-exact on a glyph). Line distance (y) dominates over
        horizontal distance (x) so a click in the gap between two
        lines resolves to the nearer LINE first, matching how every
        real text editor's click-to-position behaves, rather than
        picking whichever word happens to be geometrically closest in
        raw Euclidean distance (which can jump to an adjacent line's
        word if a page's line-height is tight relative to word gaps).
        Used by _on_drag to turn an anchor+cursor pair into a
        continuous reading-order selection range -- see its own
        docstring for why this replaced a plain rectangle-intersection
        test."""
        for i, w in enumerate(words):
            if w[0] <= x <= w[2] and w[1] <= y <= w[3]:
                return i
        best_i, best_key = 0, None
        for i, w in enumerate(words):
            line_dist = abs((w[1] + w[3]) / 2 - y)
            x_dist = 0.0 if w[0] <= x <= w[2] else min(abs(w[0] - x), abs(w[2] - x))
            key = (line_dist, x_dist)
            if best_key is None or key < best_key:
                best_key, best_i = key, i
        return best_i

    def _canvas_to_pdf_rect(self, x0, y0, x1, y1, page_num=None) -> fitz.Rect:
        z = self.viewer.zoom
        if page_num is None:
            page_num = self.viewer.page_num
        ox, oy = self._page_offset(page_num)
        cx0, cy0 = min(x0, x1) - ox, min(y0, y1) - oy
        cx1, cy1 = max(x0, x1) - ox, max(y0, y1) - oy
        return fitz.Rect(cx0 / z, cy0 / z, cx1 / z, cy1 / z)

    def _event_canvas_xy(self, event):
        """event.x/event.y are VIEWPORT-relative, not true canvas-space
        coordinates -- identical the whole time the canvas was never
        scrollable, which is exactly why this bug was invisible until
        now. Real scrollbars mean every click/drag handler needs this
        conversion or redaction/annotate/text-select/forms/textedit
        all silently misplace by the current scroll offset the moment
        the view isn't sitting at the top-left origin."""
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _on_press(self, event):
        if self._autoscroll_active:
            # Left-click while autoscrolling cancels it (browser
            # convention) instead of ALSO starting a text-selection
            # drag at the same time.
            self._stop_autoscroll()
            return
        cx, cy = self._event_canvas_xy(event)
        if self._layout is not None:
            # Translate back to the layout's own absolute coordinate
            # space before hit-testing -- static mode draws its row
            # translated to canvas origin (_static_row_offset), so a
            # raw canvas click needs the same translation undone to
            # match against self._layout's true page rects. Always
            # (0, 0) in continuous mode, so this is a no-op there.
            ox, oy = self._static_row_offset
            page_num = self._layout.page_at(cx + ox, cy + oy)
            if page_num is None:
                # Clicked in the inter-page gap -- not an error, just a
                # no-op gesture, same as clicking blank margin anywhere.
                self._drag_start = None
                return
        else:
            page_num = self.viewer.page_num
        self._drag_page = page_num
        # Keep a persistent reference for the whole gesture (same
        # weak-ref gotcha as render()'s self.page comment above) -- a
        # continuous-mode click can land on any visible page, not just
        # self.viewer.page_num, so this may differ from render()'s
        # self.page until the next render() call.
        self.page = self.doc[page_num]
        self._drag_start = (cx, cy)
        # Anchor point for a real text-flow selection -- fixed for the
        # whole gesture, in PDF space so it survives scrolling.
        rect = self._canvas_to_pdf_rect(cx, cy, cx, cy, page_num)
        self._drag_anchor_pdf = (rect.x0, rect.y0)
        if self.mode == "forms":
            self._handle_form_click(cx, cy)
            self._drag_start = None
        elif self.mode == "textedit":
            self._handle_textedit_click(cx, cy)
            self._drag_start = None
        elif self.mode == "view" and self._selected_words:
            # Starting a fresh click/drag clears any existing selection
            # (standard text-select convention -- a plain click
            # elsewhere deselects, same as any text editor/browser).
            self._selected_words = []
            self.render()

    def _on_drag(self, event):
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        cx, cy = self._event_canvas_xy(event)
        if self.mode == "view":
            # Real text-FLOW selection, not a geometric rectangle-
            # intersection test. Plain rect-intersection against every
            # word on the page selects every line the drag's bounding
            # box happens to cross, even lines/paragraphs only partly
            # overlapped -- reads as several disconnected lines
            # highlighting at once. Restricting to whichever single
            # line sits nearest the CURRENT cursor position fixes that,
            # but makes the highlight jump from line to line as the
            # mouse moves instead of accumulating a continuous run --
            # not how a real highlighter/text selection works.
            #
            # Fix: PyMuPDF's get_text("words") is already in natural
            # reading order (top-to-bottom, left-to-right) -- find the
            # word index nearest the drag's ANCHOR (mouse-down point,
            # pinned in self._drag_anchor_pdf) and the word index
            # nearest the CURRENT cursor, then select every word between
            # those two indices in reading order, regardless of which
            # one is temporally first (dragging upward just swaps which
            # index is "start"). _draw_text_selection_for_page already
            # groups the result by (block_no, line_no) into one bar per
            # line -- a partial first/last line and full middle lines
            # fall out of that grouping for free once the word RANGE
            # itself is a continuous reading-order span instead of a
            # rectangle test.
            #
            # self.doc[self._drag_page], NOT self.page -- render() (called
            # at the end of this same method, every mouse-move) unconditionally
            # resyncs self.page to self.viewer.page_num, which in continuous
            # mode is very often a DIFFERENT page than the one being dragged
            # on.
            #
            # self._selected_words holds (page_num, word) pairs instead
            # of bare words, so a selection can span every page it
            # visually crosses in continuous scroll, not just the one
            # the drag started on. cursor_page is which page the mouse
            # is CURRENTLY over (None in the inter-page gap, or in
            # static/single-page mode where there's nothing else to drag
            # onto) -- equal to self._drag_page in the common single-page
            # case, which keeps that path's exact original behavior.
            ox, oy = self._static_row_offset
            cursor_page = self._layout.page_at(cx + ox, cy + oy) if self._layout is not None else self._drag_page
            if cursor_page is None or cursor_page == self._drag_page:
                words = self.doc[self._drag_page].get_text("words")
                if not words:
                    self._selected_words = []
                else:
                    ax, ay = self._drag_anchor_pdf
                    cur = self._canvas_to_pdf_rect(cx, cy, cx, cy, self._drag_page)
                    i_anchor = self._word_index_near_point(words, ax, ay)
                    i_current = self._word_index_near_point(words, cur.x0, cur.y0)
                    lo, hi = sorted((i_anchor, i_current))
                    self._selected_words = [(self._drag_page, w) for w in words[lo:hi + 1]]
            else:
                # Dragged onto a different page. Forward (cursor_page >
                # anchor page): anchor word to the end of the anchor
                # page, every word on every fully-spanned page in
                # between, anchor-word-to-cursor-word on the final page.
                # Backward (dragging back up past where it started) is
                # the mirror image. Anchor/cursor word index is always
                # found within EACH page's own word list, in that page's
                # own PDF space -- never extrapolated across a page
                # boundary the way the old single-page code implicitly
                # did (which is what made this restriction real in the
                # first place).
                anchor_words = self.doc[self._drag_page].get_text("words")
                ax, ay = self._drag_anchor_pdf
                i_anchor = self._word_index_near_point(anchor_words, ax, ay) if anchor_words else 0
                cursor_words = self.doc[cursor_page].get_text("words")
                cur = self._canvas_to_pdf_rect(cx, cy, cx, cy, cursor_page)
                i_cursor = self._word_index_near_point(cursor_words, cur.x0, cur.y0) if cursor_words else 0
                forward = cursor_page > self._drag_page
                selected = []
                if forward:
                    selected += [(self._drag_page, w) for w in anchor_words[i_anchor:]]
                    for pn in range(self._drag_page + 1, cursor_page):
                        selected += [(pn, w) for w in self.doc[pn].get_text("words")]
                    selected += [(cursor_page, w) for w in cursor_words[:i_cursor + 1]]
                else:
                    selected += [(cursor_page, w) for w in cursor_words[i_cursor:]]
                    for pn in range(cursor_page + 1, self._drag_page):
                        selected += [(pn, w) for w in self.doc[pn].get_text("words")]
                    selected += [(self._drag_page, w) for w in anchor_words[:i_anchor + 1]]
                self._selected_words = selected
            self.render()
            return
        if self._drag_rect_id:
            self.canvas.delete(self._drag_rect_id)
        self._drag_rect_id = self.canvas.create_rectangle(
            x0, y0, cx, cy, outline="red", width=2
        )

    def _on_release(self, event):
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        self._drag_start = None
        cx, cy = self._event_canvas_xy(event)
        if self.mode == "view":
            return  # selection already computed live in _on_drag
        if self._drag_rect_id:
            self.canvas.delete(self._drag_rect_id)
            self._drag_rect_id = None
        rect = self._canvas_to_pdf_rect(x0, y0, cx, cy, self._drag_page)
        if rect.is_empty or rect.width < 3 or rect.height < 3:
            return  # treat as a click, not a drag

        page = self.page
        if self.mode == "redact":
            # No modal popup here on purpose: this fires on every single
            # drag, and a blocking messagebox per mark is bad flow for a
            # multi-region redaction pass (and makes this code path
            # fragile to test/automate -- a blocking dialog with nothing
            # there to dismiss it hangs headless runs). render()'s own
            # status bar already shows the pending count for the current
            # page; that's the real, non-blocking feedback.
            # self.page.number (not self.viewer.page_num): a latent bug,
            # invisible in single-page mode where they're always equal,
            # real the moment a drag can land on any visible page
            # (continuous mode).
            self._pending_redactions.append((self.page.number, rect))
        elif self.mode == "annotate:highlight":
            annotate.add_highlight(page, rect)
        elif self.mode == "annotate:rect":
            annotate.add_rect_shape(page, rect)
        elif self.mode == "annotate:freetext":
            text = simpledialog.askstring("Freetext note", "Note text:", parent=self.root)
            if text:
                annotate.add_freetext(page, rect, text)
        elif self.mode == "annotate:stamp":
            annotate.add_stamp(page, rect)
        self.render()

    def _handle_form_click(self, cx, cy):
        z = self.viewer.zoom
        ox, oy = self._page_offset(self._drag_page)
        px, py = (cx - ox) / z, (cy - oy) / z
        page = self.page
        for w in page.widgets():
            if w.rect.contains(fitz.Point(px, py)):
                self._fill_widget_dialog(page, w)
                return
        messagebox.showinfo("No field here", "No form field at that location.")

    def _fill_widget_dialog(self, page, widget):
        ftype = widget.field_type_string
        if ftype in ("Text",):
            val = simpledialog.askstring(
                "Fill field", f"{widget.field_name}:", parent=self.root
            )
            if val is not None:
                forms.set_text(widget, val)
        elif ftype == "CheckBox":
            checked = messagebox.askyesno("Fill field", f"Check '{widget.field_name}'?")
            forms.set_checkbox(widget, checked)
        elif ftype == "RadioButton":
            states = widget.button_states()["normal"]
            on_values = [s for s in states if s != "Off"]
            val = simpledialog.askstring(
                "Fill field",
                f"{widget.field_name} -- choose one of {on_values} (or Off):",
                parent=self.root,
            )
            if val:
                forms.set_radio(widget, val)
        elif ftype in ("ComboBox", "ListBox"):
            val = simpledialog.askstring(
                "Fill field",
                f"{widget.field_name} -- choose one of {widget.choice_values}:",
                parent=self.root,
            )
            if val is not None:
                forms.set_value(widget, val)
        self.render()

    # ------------------------------------------------------------------
    # file operations
    # ------------------------------------------------------------------
    def open_file(self):
        code_pattern = " ".join(f"*{ext}" for ext in CODE_TEXT_EXTENSIONS)
        path = filedialog.askopenfilename(filetypes=[
            ("PDF, ebook, HTML, image and code/text files",
             "*.pdf *.epub *.mobi *.fb2 *.cbz *.txt *.md *.html *.htm *.png *.jpg *.jpeg *.gif *.bmp *.tiff "
             + code_pattern),
            ("PDF files", "*.pdf"),
            ("Ebook files", "*.epub *.mobi *.fb2 *.cbz *.txt *.md"),
            ("Code/text files", code_pattern),
            ("All files", "*.*"),
        ])
        if not path:
            return
        self._open_document(path)

    def save(self):
        if not self._require_doc():
            return
        if not self.path.lower().endswith(".pdf"):
            # self.path is the ORIGINAL path (tab convention) even when
            # the actual open document is a
            # converted temp PDF (convert.path_to_pdf) -- a plain Save
            # on an HTML-sourced tab would silently overwrite the
            # original .html source file with PDF binary content.
            # There's no correct "save back to the original format"
            # here, so always force Save As instead of ever writing to
            # a non-.pdf self.path.
            self.save_as()
            return
        io_pdf.backup_before_write(self.path)
        io_pdf.safe_save(self.doc, self.path)
        messagebox.showinfo("Saved", f"Saved to {self.path}")

    def save_as(self):
        if not self._require_doc():
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf")
        if not out:
            return
        io_pdf.safe_save(self.doc, out)
        messagebox.showinfo("Saved", f"Saved to {out}")

    def apply_redactions(self):
        if not self._require_doc():
            return
        if not self._pending_redactions:
            messagebox.showinfo("Nothing to apply", "No redactions have been marked yet.")
            return
        if not messagebox.askyesno(
            "Apply redactions?",
            f"This will permanently and irreversibly remove content in "
            f"{len(self._pending_redactions)} marked region(s), and cannot be "
            f"undone. A backup of the current file will be made first. Continue?",
        ):
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", title="Save redacted copy as")
        if not out:
            return
        io_pdf.backup_before_write(self.path)
        redact.redact_and_save(self.doc, self._pending_redactions, out)
        self._pending_redactions = []
        messagebox.showinfo("Redacted", f"Saved redacted copy to {out}")
        self._open_document(out)

    def do_merge(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if not paths:
            return
        merged = merge_split.merge_pdfs(list(paths))
        out = filedialog.asksaveasfilename(defaultextension=".pdf", title="Save merged PDF as")
        if out:
            io_pdf.safe_save(merged, out)
            messagebox.showinfo("Merged", f"Saved merged PDF to {out}")
        merged.close()

    def do_split(self):
        if not self._require_doc():
            return
        out_dir = filedialog.askdirectory(title="Choose output directory")
        if not out_dir:
            return
        parts = merge_split.split_pdf(self.doc)
        base = os.path.splitext(os.path.basename(self.path))[0]
        for i, part in enumerate(parts):
            io_pdf.safe_save(part, os.path.join(out_dir, f"{base}_p{i + 1}.pdf"))
            part.close()
        messagebox.showinfo("Split", f"Wrote {len(parts)} single-page files to {out_dir}")

    def do_scan_document(self):
        if not self._require_doc():
            return
        hits = scan.scan_document(self.doc)
        real_hits = [h for h in hits if h["kind"] != "unscannable"]
        unscannable_pages = [h["page"] for h in hits if h["kind"] == "unscannable"]

        lines = []
        if real_hits:
            for h in real_hits:
                lines.append(f"page {h['page'] + 1}: [{h['kind']}] {h['context']}")
        else:
            lines.append("Nothing sensitive-shaped found.")
        if unscannable_pages:
            pages_str = ", ".join(str(p + 1) for p in unscannable_pages)
            lines.append(
                f"\n{len(unscannable_pages)} page(s) have no extractable text "
                f"(image-only? needs OCR, not checked): {pages_str}"
            )

        top = tk.Toplevel(self.root)
        top.title("Scan results")
        text = tk.Text(top, width=90, height=20, wrap="word")
        text.insert("1.0", "\n".join(lines))
        text.config(state="disabled")
        text.pack(fill=tk.BOTH, expand=True)

        markable = [h for h in real_hits if h["rect"] is not None]
        if markable:
            def mark_all():
                for h in markable:
                    self._pending_redactions.append((h["page"], h["rect"]))
                messagebox.showinfo(
                    "Marked", f"{len(markable)} region(s) marked for redaction -- "
                    "use Edit > Apply pending redactions to finish."
                )
                top.destroy()
                self.render()

            tk.Button(top, text=f"Mark all {len(markable)} hit(s) for redaction", command=mark_all).pack(
                pady=6
            )

        self._paint_widget(top, theme.get_palette(self.theme_name.get()))

    def do_scan_folder(self):
        directory = filedialog.askdirectory(title="Choose a folder to scan for sensitive PDFs")
        if not directory:
            return
        results = scan.scan_directory(directory)
        if not results:
            messagebox.showinfo("Scan folder", "No sensitive-shaped content found in any PDF.")
            return
        lines = []
        for filename, hits in results.items():
            real_hits = [h for h in hits if h["kind"] != "unscannable"]
            unscannable = [h for h in hits if h["kind"] == "unscannable"]
            parts = []
            if real_hits:
                kinds = ", ".join(sorted({h["kind"] for h in real_hits}))
                parts.append(f"{len(real_hits)} hit(s): {kinds}")
            if unscannable:
                parts.append(f"{len(unscannable)} unscannable page(s)")
            lines.append(f"{filename}: {'; '.join(parts)}")

        top = tk.Toplevel(self.root)
        top.title(f"Scan results — {directory}")
        text = tk.Text(top, width=100, height=25, wrap="word")
        text.insert("1.0", "\n".join(lines))
        text.config(state="disabled")
        text.pack(fill=tk.BOTH, expand=True)
        self._paint_widget(top, theme.get_palette(self.theme_name.get()))

    # ------------------------------------------------------------------
    # convert (office-doc utilities: PDF <-> markdown/text/images) --
    # read-only exports work on any open document (PDF or ebook), same
    # as Scan; not gated by _update_pdf_only_menu_state.
    # ------------------------------------------------------------------
    def do_export_markdown(self):
        if not self._require_doc():
            return
        out = filedialog.asksaveasfilename(defaultextension=".md", title="Export to Markdown as")
        if not out:
            return
        md = convert.pdf_to_markdown(self.doc)
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        messagebox.showinfo("Exported", f"Saved Markdown to {out}")

    def do_export_text(self):
        if not self._require_doc():
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt", title="Export as plain text as")
        if not out:
            return
        text = convert.pdf_to_text(self.doc)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        messagebox.showinfo("Exported", f"Saved text to {out}")

    def do_export_images(self):
        if not self._require_doc():
            return
        out_dir = filedialog.askdirectory(title="Choose output directory for page images")
        if not out_dir:
            return
        base_name = os.path.splitext(os.path.basename(self.path))[0]
        written = convert.pdf_to_images(self.doc, out_dir, base_name)
        messagebox.showinfo("Exported", f"Wrote {len(written)} image(s) to {out_dir}")

    def do_import_images(self):
        paths = filedialog.askopenfilenames(
            title="Choose images to combine into a PDF (in order)",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp")],
        )
        if not paths:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", title="Save combined PDF as")
        if not out:
            return
        pdf = convert.images_to_pdf(list(paths))
        io_pdf.safe_save(pdf, out)
        pdf.close()
        messagebox.showinfo("Imported", f"Saved {len(paths)} image(s) as {out}")
        self._open_document(out)

    # ------------------------------------------------------------------
    # Read Aloud (TTS)
    # ------------------------------------------------------------------
    def _ensure_voice_available(self, voice_id: str) -> bool:
        """True if usable (already bundled/downloaded, or just
        downloaded now). Downloads run on a background thread with a
        real progress dialog -- these are ~60MB fetches, blocking the
        UI for that would be bad. wait_window() makes this call itself
        synchronous from the caller's point of view even though the
        download isn't."""
        if tts.is_available(voice_id):
            return True

        label = tts.VOICES[voice_id]["label"]
        if not messagebox.askyesno(
            "Download voice?",
            f"'{label}' has not been downloaded yet (~60MB, one-time, "
            f"cached for future use). Download it now?",
        ):
            return False

        progress_top = tk.Toplevel(self.root)
        progress_top.title(f"Downloading {label}...")
        progress_top.resizable(False, False)
        progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(progress_top, variable=progress_var, maximum=100, length=300).pack(
            padx=20, pady=(20, 8)
        )
        status_label = tk.Label(progress_top, text="Starting...")
        status_label.pack(pady=(0, 16))
        self._paint_widget(progress_top, theme.get_palette(self.theme_name.get()))

        result = {"done": False, "error": None}
        # Tkinter is not thread-safe -- calling self.root.after(...)
        # FROM the worker thread raises "main thread is not in main
        # loop". The worker only ever writes to this plain dict
        # (simple attribute assignment, safe enough for a single-
        # producer/single-consumer read); poll(), scheduled via
        # self.root.after() and therefore always running on the MAIN
        # thread, is the only thing that ever touches real widgets.
        progress = {"pct": 0.0}

        def on_progress(done_bytes, total_bytes):
            progress["pct"] = (done_bytes / total_bytes * 100) if total_bytes else 0.0

        def worker():
            try:
                tts.download_voice(voice_id, progress_callback=on_progress)
            except Exception as e:
                result["error"] = str(e)
            result["done"] = True

        def poll():
            progress_var.set(progress["pct"])
            status_label.config(text=f"{progress['pct']:.0f}%")
            if result["done"]:
                if progress_top.winfo_exists():
                    progress_top.destroy()
                return
            self.root.after(100, poll)

        threading.Thread(target=worker, daemon=True).start()
        poll()
        self.root.wait_window(progress_top)

        if result["error"]:
            messagebox.showinfo("Download failed", result["error"])
            return False
        return tts.is_available(voice_id)

    def do_read_page(self):
        """Menu 'Read this page' / toolbar quick-play -- explicitly a
        single-page read. Cancels any in-progress "read entire
        document" auto-continuation (do_read_document) so switching
        back to a plain single-page read doesn't keep auto-advancing
        afterward."""
        self._tts_reading_document = False
        self._read_current_page()

    def do_read_document(self):
        """Reads from the current page onward, not just the current
        page, auto-advancing (page nav + the reading-position highlight both
        follow, via _go_to_page) as each page's audio naturally
        finishes -- until the end of the document or Stop. Blank
        pages encountered while auto-advancing are skipped silently
        (see _advance_to_next_page_and_continue_reading) rather than
        interrupting a hands-free read with a dialog; the page you
        explicitly started on still gets the normal "nothing to read"
        message if it's blank, same as "Read this page" always has."""
        self._tts_reading_document = True
        self._read_current_page()

    def _read_current_page(self):
        """Real perf finding: synthesis alone (even with a warm, cached
        voice -- see tts.py's _voice_cache) takes on the order of a
        second or more for a normal page of text. Running that
        synchronously on the main thread freezes the whole UI for the
        duration. Synthesis instead runs on a background thread; poll()
        (scheduled via self.root.after(),
        so it always runs on the main thread -- same real bug already
        fixed once for the download flow) picks up the result and does
        the actual playback."""
        if not self._require_doc():
            return
        words = self.page.get_text("words")
        if not words:
            messagebox.showinfo("Nothing to read", "This page has no extractable text.")
            return
        self._speak_text(words, self.page, self.viewer.page_num)

    def _read_from_word_click(self, event):
        """Right-click a word in view mode -> "Read from here", same
        right-click-picks-the-item-under-the-cursor convention as the
        home screen's recent-files context menu. Reuses
        _word_index_near_point (the same nearest-word lookup drag-
        selection already relies on) to find where the click landed,
        then reads from that word to the end of the page -- a coarser
        granularity than the selection highlight's exact ranges, but
        matches how a reader actually thinks about "start reading
        here": from this point in the page onward, not word-perfect."""
        if self.mode != "view" or not self._require_doc():
            return
        cx, cy = self._event_canvas_xy(event)
        ox, oy = self._static_row_offset
        page_num = self._layout.page_at(cx + ox, cy + oy) if self._layout is not None else self.viewer.page_num
        if page_num is None:
            return
        page = self.doc[page_num]
        words = page.get_text("words")
        if not words:
            messagebox.showinfo("Nothing to read", "This page has no extractable text.")
            return
        click_pdf = self._canvas_to_pdf_rect(cx, cy, cx, cy, page_num)
        i = self._word_index_near_point(words, click_pdf.x0, click_pdf.y0)
        self._speak_text(words[i:], page, page_num)

    def _speak_text(self, words, page, page_num):
        """Shared synthesis+playback kickoff for both a whole-page read
        (_read_current_page) and a from-this-point read
        (_read_from_word_click) -- everything past "what words and which
        page" is identical between the two. Takes the real word-tuple
        list actually being spoken (not a page number's worth of
        already-known-good text) so _update_tts_highlight can track
        progress against the SAME words that were actually synthesized:
        re-deriving the FULL page's words from scratch would be
        oblivious to a "read from here" click trimming the start, so
        the progress estimate would race through words that were never
        even sent to the synthesizer."""
        if getattr(self, "_tts_synthesizing", False):
            return  # a previous read is still being synthesized
        text = " ".join(w[4] for w in words)

        # Captured for _update_tts_highlight's position estimate -- the
        # actual page being read stays fixed even if the user scrolls/
        # navigates elsewhere while listening (self.page would drift).
        self._tts_reading_page = page
        self._tts_reading_page_num = page_num
        self._tts_reading_words = words

        voice_id = self.tts_voice.get()
        if not self._ensure_voice_available(voice_id):
            return

        # tts.speed_to_length_scale (not a plain 1.0/speed inverse):
        # "1.0x" is a calibrated natural default, not Piper's raw
        # native rate.
        length_scale = tts.speed_to_length_scale(self.tts_speed.get())
        self._tts_synthesizing = True
        self.status.config(text="Synthesizing speech...")
        result = {"done": False, "audio": None, "error": None}

        def worker():
            try:
                result["audio"] = tts.synthesize(text, voice_id, length_scale)
            except Exception as e:
                result["error"] = str(e)
            result["done"] = True

        def poll():
            if not result["done"]:
                self.root.after(50, poll)
                return
            self._tts_synthesizing = False
            self.render()  # restores the normal page/zoom status text
            if result["error"]:
                messagebox.showinfo("Playback failed", result["error"])
                return
            audio, sample_rate, _width, channels, chunk_sample_counts = result["audio"]
            self._tts_chunk_sample_counts = chunk_sample_counts  # real per-sentence durations, see _update_tts_highlight
            try:
                self.tts_player.load(audio, sample_rate, channels)
                self.tts_player.play()
            except Exception as e:
                messagebox.showinfo("Playback failed", str(e))
            self._poll_tts_playback_state()

        # Tests polling only the _tts_synthesizing FLAG, not this actual
        # thread object, hit a razor-thin gap between the flag flipping
        # False (inside worker(), just before it returns) and the OS
        # thread genuinely finishing -- a test that only trusts the flag
        # can proceed (and tear down, letting the NEXT test's
        # main-thread Tk calls run) while this thread is still mid-
        # teardown after its first-ever `import piper`, a cross-test
        # race that segfaults. self._tts_thread is kept so tests can
        # .join() it for a real guarantee, not just the flag.
        self._tts_thread = threading.Thread(target=worker, daemon=True)
        self._tts_thread.start()
        poll()

    def do_tts_pause_resume(self):
        if self.tts_player.is_playing():
            self.tts_player.pause()
        else:
            try:
                self.tts_player.play()
            except Exception as e:
                messagebox.showinfo("Playback failed", str(e))
        self._poll_tts_playback_state()

    def do_tts_stop(self):
        # Player.stop() deliberately rewinds rather than unloads (its
        # own docstring: "Unlike pause(), resets position to the
        # start") -- has_audio() stays True on purpose, so a
        # subsequent play() replays this same page from 0 instead of
        # needing a fresh "Read this page". _tts_reading_page/_num
        # stay set to match -- the highlight correctly redraws at the
        # first word (progress 0.0) rather than disappearing.
        self.tts_player.stop()
        self._tts_reading_document = False  # explicit Stop always cancels auto-advance
        self._update_tts_ui()

    def do_tts_toggle_play(self):
        """Toolbar quick-access button -- one button that does whichever
        action makes sense right now instead of making the user pick
        the right menu command: starts reading the current page if
        nothing's loaded yet, otherwise toggles pause/resume of what's
        already loaded."""
        if self.tts_player.has_audio():
            self.do_tts_pause_resume()
        else:
            self.do_read_page()

    def _on_tts_voice_changed(self):
        """The Voice menu's radiobuttons had no command callback at
        all -- selecting a different voice only updated the tts_voice
        StringVar, with nothing to actually apply it. Whatever was
        already loaded (or mid-synthesis) just kept playing in the OLD
        voice with no way to hear the new selection short of manually
        stopping and clicking "Read this page" again. If something is
        already loaded, selecting a voice restarts the CURRENT page
        fresh in the new one -- do_read_page() already stops old
        playback itself (Player.load()'s own stop() call). Mid-
        synthesis (audio not loaded yet) is a real, accepted gap left
        for later: do_read_page()'s own _tts_synthesizing guard would
        block a same-instant re-trigger, and synthesis is fast enough
        (~1s) that this is a narrow window."""
        settings.save({"tts_voice": self.tts_voice.get()})
        if self.tts_player.has_audio():
            self.do_read_page()

    def _on_tts_speed_changed(self):
        """Speed menu's radiobuttons had no command callback at all
        (only Voice's did, see _on_tts_voice_changed above) -- added
        purely to persist the choice, matching that same fix's own
        precedent. Unlike voice, changing the speed mid-read doesn't
        need to restart anything: length_scale only takes effect at the
        next synthesize() call, and there's no equivalent live bug
        report asking for an immediate restart here."""
        settings.save({"tts_speed": self.tts_speed.get()})

    def _update_tts_toolbar_button(self):
        if not hasattr(self, "tts_play_button"):
            return  # home screen, no doc-view toolbar built yet
        self.tts_play_button.config(text="⏸" if self.tts_player.is_playing() else "▶")

    def _tts_status_text(self) -> str:
        """Voice name + speed multiplier, shown only while something is
        actually loaded (empty otherwise, so it doesn't clutter the
        toolbar the rest of the time)."""
        if not self.tts_player.has_audio():
            return ""
        voice_label = tts.VOICES.get(self.tts_voice.get(), {}).get("label", self.tts_voice.get())
        return f"\U0001F50A {voice_label} · {self.tts_speed.get():g}x"

    def _update_tts_highlight(self):
        """A "follow along" highlight for what's currently being read,
        using the house green accent (the one other place, besides
        text selection, green is allowed to appear per the manga-
        essence minimal-accent rule).

        Honest limitation, not hidden: Piper's simple synthesize() API
        (tts.py) returns raw audio only, no per-word timing/alignment
        data -- there's no real way to know exactly which word is
        playing at any instant. Estimated as a fraction of the page's
        text proportional to Player.progress (0.0-1.0 through the
        audio), weighted by CHARACTER count rather than plain word
        count -- a 12-letter word takes noticeably longer to speak
        than "a", so a per-word index alone drifts visibly out of
        sync over a page; a character-weighted cumulative position is
        still an estimate (no true audio alignment exists to check
        against) but tracks materially better.

        Drawn as ONE merged rectangle over words sharing the current
        line, not 2-3 separate small stippled boxes -- separate boxes
        visibly fragment (and can jump to the start of the NEXT line
        mid-window, drawing two disconnected boxes) instead of reading
        as one smooth highlight. Constraining the window to one line
        (PyMuPDF's own line_no field) and merging into a single
        rectangle fixes the fragmentation.

        Built as a genuinely translucent RGBA PhotoImage rather than a
        stippled rectangle. Tk canvas fill colors have no alpha
        channel; `stipple` is Tk's only built-in fake-transparency
        trick, and it works by literally not painting ~75% of the
        pixels in a fixed dot pattern, which reads as rasterized
        because it is. Tk 8.6+ canvas images DO alpha-composite for
        real against whatever's already drawn underneath, giving a
        true semi-transparent highlighter color over the text instead
        of a dither pattern.

        Cleared (canvas.delete by tag) whenever nothing's loaded, or
        when the page being read isn't part of what's currently drawn
        (scrolled/navigated away -- nothing to overlay onto)."""
        self.canvas.delete("tts_highlight")
        page_num = self._tts_reading_page_num
        if page_num is None or not self.tts_player.has_audio() or self._tts_reading_page is None:
            return
        if self._layout is not None and page_num not in self._last_window:
            return  # not currently drawn -- nothing to overlay onto
        # self._tts_reading_words, NOT a fresh
        # self._tts_reading_page.get_text("words") -- the latter would
        # silently ignore a "read from here" start offset, estimating
        # progress against every word on the page instead of only the
        # ones actually sent to the synthesizer.
        words = self._tts_reading_words
        if not words:
            return
        # Piper inserts a genuine pause at sentence ends and a much
        # smaller one at clause breaks -- real elapsed audio time
        # producing zero new characters of speech; a flat +1-per-word
        # model charges punctuation the same time-cost as any letter,
        # implicitly assuming pauses take no time. Weights below are
        # MEASURED, not guessed: headless A/B synthesis via this exact
        # voice/length_scale (northern_english_male, 1.0x), holding word
        # content fixed and comparing a sentence-final period against a
        # mid-sentence comma at the identical position, then solving
        # for the extra pause time in character-equivalents. Result: a
        # period costs ~9.3 char-equivalents of pause; a comma costs
        # only ~0.7.
        def _char_weight(word_text):
            n = len(word_text) + 1  # +1 for the trailing space/gap
            if word_text.endswith((".", "!", "?")):
                n += 9  # sentence-end pause, measured ~9.3
            elif word_text.endswith((",", ";", ":")):
                n += 1  # clause-break pause, measured ~0.7 -- nearly negligible
            return n

        def _weighted_local_idx(word_list, fraction):
            """Char-weighted position estimate scoped to whatever word
            list is passed in -- the same math as before this pass,
            just reusable for both the per-sentence path and the
            whole-page fallback below."""
            counts = [_char_weight(w[4]) for w in word_list]
            total = sum(counts)
            if total <= 0:
                return 0
            target = fraction * total
            seen = 0
            for i, n in enumerate(counts):
                if seen + n > target:
                    return i
                seen += n
            return len(word_list) - 1

        # Per-SENTENCE calibration. True per-phoneme alignment isn't
        # available: these voice models' ONNX sessions return only one
        # output tensor (audio), so `include_alignments=True` yields
        # nothing to use -- tts.synthesize() has no duration-output
        # branch for it. What IS available: Piper synthesizes one audio
        # chunk per SENTENCE, and tts.synthesize() returns each chunk's
        # real sample count (self._tts_chunk_sample_counts, set in
        # _read_current_page). Grouping `words` into sentences
        # (splitting after any word ending in .!?) and pairing each
        # group 1:1 with a real chunk duration turns "one uniform
        # character-rate guess across the WHOLE PAGE" into "one uniform
        # rate per SENTENCE, with real measured pauses between them" --
        # a much smaller, more honest approximation window.
        #
        # The sentence split is a simple heuristic and won't always
        # match Piper/espeak's own internal sentence boundaries -- an
        # abbreviation like "vv." or "Jer." can fool it into splitting
        # where espeak didn't. Rather than silently mismatching chunk N
        # to the wrong sentence, the sentence COUNT is checked against
        # the real chunk count first; any mismatch falls back to the
        # same whole-page weighted estimate this function already used
        # (still real, still correctly calibrated punctuation weights --
        # just without per-sentence pause precision).
        chunk_counts = self._tts_chunk_sample_counts
        sentence_groups = None
        if chunk_counts:
            groups, current = [], []
            for w in words:
                current.append(w)
                if w[4].endswith((".", "!", "?")):
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)
            if len(groups) == len(chunk_counts):
                sentence_groups = groups

        if sentence_groups is not None:
            total_samples = sum(chunk_counts)
            position_samples = self.tts_player.progress * total_samples
            cumulative = 0
            sentence_idx = len(chunk_counts) - 1
            fraction_within = 1.0
            for i, count in enumerate(chunk_counts):
                if position_samples < cumulative + count:
                    sentence_idx = i
                    fraction_within = (position_samples - cumulative) / count if count > 0 else 0.0
                    break
                cumulative += count
            sentence_words = sentence_groups[sentence_idx]
            local_idx = _weighted_local_idx(sentence_words, fraction_within)
            offset = sum(len(g) for g in sentence_groups[:sentence_idx])
            idx = offset + local_idx
        else:
            idx = _weighted_local_idx(words, self.tts_player.progress)
        anchor = words[idx]
        anchor_block, anchor_line = anchor[5], anchor[6]
        # Same line only, TRAILING up to 5 words ending AT idx (not
        # leading from idx) -- a handful of words never spilling onto
        # the PREVIOUS line. words[idx:idx+6] (the current word PLUS
        # the next 5) makes the highlight's leading edge always show 5
        # words not yet spoken, reading as "racing ahead of the audio."
        # A trailing window (already-spoken words ending at the current estimate)
        # keeps the same "one merged rectangle, not a choppy single
        # word" goal without visually promising unspoken content.
        window = []
        for w in reversed(words[max(0, idx - 5):idx + 1]):
            if w[5] != anchor_block or w[6] != anchor_line:
                break
            window.append(w)
        if not window:
            window = [anchor]
        ox, oy = self._page_offset(page_num)
        z = self.viewer.zoom
        colors = theme.get_palette(self.theme_name.get())
        x0 = min(w[0] for w in window)
        y0 = min(w[1] for w in window)
        x1 = max(w[2] for w in window)
        y1 = max(w[3] for w in window)
        px0, py0 = ox + x0 * z, oy + y0 * z
        px1, py1 = ox + x1 * z, oy + y1 * z
        w, h = max(1, round(px1 - px0)), max(1, round(py1 - py0))
        hexc = colors["highlight_bg"].lstrip("#")
        r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
        overlay = Image.new("RGBA", (w, h), (r, g, b, 90))  # ~35% opacity
        self._tts_highlight_photo = ImageTk.PhotoImage(overlay)  # keep ref, Tk drops GC'd images
        self.canvas.create_image(px0, py0, anchor="nw", image=self._tts_highlight_photo, tags=("tts_highlight",))

    def _update_tts_ui(self):
        self._update_tts_toolbar_button()
        if hasattr(self, "tts_status_label"):
            self.tts_status_label.config(text=self._tts_status_text())
        self._update_tts_highlight()

    def _poll_tts_playback_state(self):
        """Keeps the toolbar button/status/highlight accurate across
        state changes nothing else calls back for -- most notably
        playback reaching the natural end of a page's audio, which the
        Player has no callback for at all (see playback.py's own note
        on sd.CallbackStop()), and the highlight's own estimated
        position, which needs to keep advancing while nothing else is
        triggering a redraw. Self-cancels once playback stops instead
        of polling forever -- except mid "read entire document",
        where reaching a real natural end (was playing, now isn't, and
        NOT because of an explicit pause --
        Player.is_paused() is the real distinguishing check) triggers
        _advance_to_next_page_and_continue_reading instead of just
        stopping. That call itself re-triggers a fresh poll loop once
        the next page's audio starts, so the chain keeps going on its
        own without this method needing to reschedule itself through it."""
        was_playing = self._tts_was_playing
        is_playing_now = self.tts_player.is_playing()
        self._tts_was_playing = is_playing_now
        self._update_tts_ui()
        if (
            was_playing and not is_playing_now and not self.tts_player.is_paused()
            and getattr(self, "_tts_reading_document", False)
        ):
            self._advance_to_next_page_and_continue_reading()
            return
        if is_playing_now:
            self.root.after(250, self._poll_tts_playback_state)

    def _advance_to_next_page_and_continue_reading(self):
        """The real "read entire document" mechanism -- called once a
        page's audio reaches its natural end while _tts_reading_document
        is True. Blank pages are skipped silently (no "nothing to
        read" dialog -- that would interrupt a hands-free continuous
        read); reaching the end of the document just stops cleanly."""
        if self.viewer is None or self._tts_reading_page_num is None:
            self._tts_reading_document = False
            return
        next_page_num = self._tts_reading_page_num + 1
        while next_page_num < self.viewer.page_count:
            if self.doc[next_page_num].get_text().strip():
                self._go_to_page(next_page_num)
                self._read_current_page()
                return
            next_page_num += 1
        self._tts_reading_document = False  # reached the end -- nothing left to read

    def _snapshot_current_edits(self) -> str:
        """Save self.doc's current in-memory state (including any
        unsaved edits) to a FRESH temp path, never back onto self.path --
        PyMuPDF forbids a non-incremental save to the same path a
        document is already open from ("save to original must be
        incremental"), which io_pdf.safe_save's hardened incremental=False
        can never satisfy. Real bug hit live in test_integration.py:
        do_sign/do_encrypt originally tried safe_save(self.doc, self.path)
        directly and crashed with exactly that ValueError."""
        snapshot = self.path + ".slate-snapshot.pdf"
        io_pdf.safe_save(self.doc, snapshot)
        return snapshot

    def do_encrypt(self):
        if not self._require_doc():
            return
        owner_pw = simpledialog.askstring("Encrypt", "Owner password:", show="*", parent=self.root)
        if not owner_pw:
            return
        user_pw = simpledialog.askstring("Encrypt", "User password:", show="*", parent=self.root)
        if user_pw is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", title="Save encrypted copy as")
        if not out:
            return
        snapshot = self._snapshot_current_edits()
        security.encrypt(snapshot, out, owner_password=owner_pw, user_password=user_pw)
        messagebox.showinfo("Encrypted", f"Saved encrypted copy to {out}")

    def do_sign(self):
        if not self._require_doc():
            return
        if not messagebox.askyesno(
            "Sign document",
            "This uses a throwaway self-signed test certificate (fine for "
            "internal sign-off, not a substitute for a real signing cert). "
            "Signing must be the LAST edit to a document -- further changes "
            "after this will invalidate the signature. Continue?",
        ):
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", title="Save signed copy as")
        if not out:
            return
        snapshot = self._snapshot_current_edits()
        key_path = self.path + ".slate-testkey.pem"
        cert_path = self.path + ".slate-testcert.pem"
        if not (os.path.exists(key_path) and os.path.exists(cert_path)):
            sign.generate_self_signed_cert(key_path, cert_path)
        signer = sign.load_signer(key_path, cert_path)
        sign.sign(snapshot, out, signer)
        results = sign.validate(out)
        ok = all(r.intact and r.valid for r in results)
        messagebox.showinfo(
            "Signed", f"Saved signed copy to {out}\nValidation: {'OK' if ok else 'FAILED'}"
        )


def _set_windows_app_user_model_id():
    """Must run BEFORE any window (Tk root included) is created --
    Microsoft's own documented requirement for
    SetCurrentProcessExplicitAppUserModelID. Without this, Windows
    groups a python.exe-hosted Tk app under python.exe's own taskbar
    identity (and often shows python's icon, not this app's, in that
    grouped view) instead of giving Slate its own distinct taskbar
    entry. iconbitmap() alone (_set_window_icon) doesn't fix the
    grouping half, only the icon-image half. Best-effort, same
    fail-soft pattern as _apply_native_titlebar_theme.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Slate.PDFEditor")
    except Exception:
        pass


def main():
    _set_windows_app_user_model_id()
    path = sys.argv[1] if len(sys.argv) > 1 else None

    # Single-instance: if a Slate window is already
    # running, hand this path to it as a new tab instead of opening a
    # second window. Only meaningful when a path was actually given --
    # a bare `slate.py` with nothing to open has nothing to hand off.
    if path and singleinstance.try_send_to_running_instance(path):
        return

    root = tk.Tk()
    app = SlateApp(root, path)

    # Restore window size+position. A saved geometry wins outright -- it
    # already encodes both size and position together, nothing left for
    # the centering logic below to add. Only a genuine first-ever launch
    # (or a corrupt/missing settings file, load()'s own fallback) has no
    # saved value, in which case centering is still the right first-run
    # default. update_idletasks() first either way -- real geometry only
    # exists once the home
    # screen/document widgets above are actually laid out, same pattern
    # as _show_about's own centering.
    root.update_idletasks()
    saved_geometry = settings.load()["window_geometry"]
    if saved_geometry:
        root.geometry(saved_geometry)
    else:
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        win_w, win_h = root.winfo_width(), root.winfo_height()
        root.geometry(f"+{(screen_w - win_w) // 2}+{(screen_h - win_h) // 2}")

    def _on_close():
        # winfo_geometry() returns "WxHX+Y" in exactly the format
        # geometry() itself accepts -- a direct round-trip, no parsing.
        settings.save({"window_geometry": root.winfo_geometry()})
        # Final position checkpoint -- _go_to_page's
        # own checkpoints cover explicit navigation, but plain scrolling
        # in continuous mode isn't saved on every tick (real I/O cost);
        # this catches wherever that actually left things before the
        # window really closes.
        app._save_open_tabs()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    # transient()+-topmost (see _show_settings/_show_about) ties these
    # dialogs to Slate visually and keeps them grouped under Slate's own
    # taskbar entry, but neither one makes Windows actually MINIMIZE a
    # child when its owner minimizes -- topmost specifically fights
    # that, since Windows treats "stay above everything" and "hide when
    # the owner hides" as two independent, unrelated states. Without
    # this, minimizing Slate leaves Settings/About floating alone on the
    # real desktop. Watch root's own iconic state directly (<Unmap>/
    # <Map> fire on more than just minimize, so check root.state()
    # rather than trust the event alone) and drive every tracked
    # single-instance dialog's
    # iconify/deiconify in lockstep -- winfo_exists() guards each one
    # since any of them may not be open, or may have been closed
    # (destroyed) independently of a minimize/restore cycle.
    _child_dialog_attrs = ("_settings_window", "_about_window")

    def _sync_children_to_root_state(event=None):
        if event is not None and event.widget is not root:
            return  # a child Toplevel's own Unmap/Map, not root's
        iconic = root.state() == "iconic"
        for attr in _child_dialog_attrs:
            win = getattr(app, attr, None)
            if win is not None and win.winfo_exists():
                if iconic:
                    # iconify() alone isn't enough: -topmost is a
                    # WINDOW-MANAGER attribute independent of Tk's iconic
                    # state -- the same tension the module comment above
                    # names ("Windows treats 'stay above everything' and
                    # 'hide when the owner hides' as two independent,
                    # unrelated states"). A still-topmost window keeps
                    # rendering above whatever the user drags over it
                    # even once iconified, on top of every other app, not
                    # just Slate. Clear -topmost before iconifying so a minimized
                    # Settings/About behaves like any other minimized
                    # window -- restored on the way back out below.
                    win.attributes("-topmost", False)
                    win.iconify()
                else:
                    win.deiconify()
                    win.attributes("-topmost", True)

    root.bind("<Unmap>", _sync_children_to_root_state)
    root.bind("<Map>", _sync_children_to_root_state)

    # Become the server for any LATER invocation. Real thread-safety
    # note (same pattern already established for the TTS synthesis and
    # voice-download worker threads): the socket-listener thread must
    # never touch Tk widgets directly -- it only ever puts a path on a
    # plain queue.Queue; _poll_ipc (scheduled via root.after(), so it
    # always runs on the main thread) is the only thing that calls
    # _open_document.
    ipc_queue, on_path = singleinstance.make_ipc_queue()
    try:
        ipc_server = singleinstance.start_server(on_path)
    except OSError:
        # Real, rare race: another invocation won the bind between our
        # own failed try_send above and this bind call. Fail soft --
        # this instance just won't accept later hand-offs; it still
        # opens fine standalone.
        ipc_server = None

    def _poll_ipc():
        try:
            while True:
                new_path = ipc_queue.get_nowait()
                app._open_document(new_path)
                root.deiconify()
                root.lift()
        except queue.Empty:
            pass
        root.after(250, _poll_ipc)

    if ipc_server is not None:
        root.after(250, _poll_ipc)

    root.mainloop()
    if ipc_server is not None:
        ipc_server.close()
    if app.doc is not None:
        app.doc.close()


if __name__ == "__main__":
    main()
