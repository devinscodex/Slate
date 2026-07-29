#!/usr/bin/env python3
"""Slate — entry point and UI integration. Wires viewer, redact,
annotate, merge_split, forms, sign, security, scan, recent, io_pdf
together into one menu-driven app. Business logic lives in the
per-feature modules; this file is glue + Tkinter widgets only.
"""
import os
import platform
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

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
# to a mid-gray that can vanish against a dark theme's background --
# real bug, Devin screenshot 2026-07-25 ("if this is inkbone dark, i
# cannot see the menu checkboxes"), fixed for the app's Menu-based
# checkboxes at the time but never promoted to a shared constant, so
# the Settings dialog's own standalone Radiobutton/Checkbutton widgets
# (a separate code path, built later) never got it and shipped with
# the same invisible-indicator bug in Dark/Inkbone Dark -- real
# screenshot, 2026-07-28. Bright green reads against light OR dark
# backgrounds, so one fixed value here (not re-themed live) is more
# robust than tracking every radio/checkbutton through every theme
# switch -- same reasoning _build_menu already used, now shared so it
# can't drift between the two call sites again.
RADIO_SELECT_COLOR = "#4a9e3a"

# Extensions fitz/PyMuPDF would otherwise refuse outright ("Failed to open
# file '...' as type ps1" -- confirmed live 2026-07-29) because it only
# infers document type from the extension and doesn't recognize these as
# text, even though the content is byte-identical to a .txt file it opens
# fine. Passing filetype="txt" explicitly for these makes them open as
# plain monospace text (no crash, no syntax color yet -- that's a separate,
# bigger feature: a real tokenizer + per-theme color mapping, not built).
CODE_TEXT_EXTENSIONS = (
    ".ps1", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml",
    ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".css", ".sql", ".ini", ".cfg",
)

# Menu labels that only make sense for a real PDF (mutation/signing/
# forms/etc) -- disabled whenever the active tab's document isn't one.
# PyMuPDF/MuPDF (confirmed live + via its own docs feature matrix) also
# opens EPUB/MOBI/FB2/CBZ/TXT/MD natively -- view/search/TOC/keyboard
# nav all already work unchanged on those, only these PDF-specific
# actions need gating.
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
        # Set before any other widget exists (even before root.title())
        # so the very first paint already uses the right color -- real
        # ask (Devin): loading light and then visibly flashing to dark
        # a moment later, once a saved preference applies, is exactly
        # the jarring effect this line order avoids.
        root.configure(bg=theme.get_palette(theme.load_preference())["bg"])
        # Persisted user prefs (Devin, 2026-07-26 handoff): loaded once
        # here, applied below as each corresponding variable's initial
        # value instead of a hardcoded default. self._saved_zoom is kept
        # separately (not applied yet) since no Viewer/document exists
        # this early -- _open_document applies it once a doc is loaded.
        _saved = settings.load()
        self._saved_zoom = _saved["zoom"]
        self._saved_open_tabs = _saved["open_tabs"]
        self.path = None
        self.doc = None
        self.viewer = None
        self.page = None
        # Theme-colorize opt-out (Devin, 2026-07-26): _colorize_for_theme
        # deliberately flattens every page to the theme's fg/bg pair so
        # documents visually match the app chrome (2026-07-25 design
        # call) -- correct default for prose/book reading, but it
        # destroys real color content (a categorical-color-coded diagram,
        # a photo) where color IS the information. Per-session toggle,
        # default True (unchanged existing behavior) so nothing regresses
        # for the common case.
        self.colorize_pages = _saved["colorize_pages"]
        # Crop to content (Devin, 2026-07-29: "I don't like big page
        # margins, especially in book view") -- one shared crop rect
        # (viewer.detect_content_bbox) applied to every page, cached per
        # DOCUMENT (self._crop_rect, keyed by self._crop_rect_doc) since
        # sampling several pages' real text/image/drawing bboxes isn't
        # free and the result doesn't change unless the document itself
        # changes. Default off -- a display-altering feature, opt-in same
        # as colorize_pages above, not sprung on an existing workflow.
        self.crop_to_content = _saved.get("crop_to_content", False)
        self._crop_rect = None
        self._crop_rect_doc = None
        self._tk_img = None  # keep a reference or Tkinter garbage-collects it
        self.mode = "view"  # view | redact | annotate:<kind> | forms | textedit
        self._drag_start = None
        self._drag_rect_id = None
        self._corner_grip_start = None  # (start mouse x/y, start window w/h) for the bottom-right resize grip
        self._pending_redactions = []  # [(page_num, fitz.Rect), ...]
        # Text selection (view mode default -- Devin's ask, 2026-07-25:
        # "default to arrow/select text over rectangle select"). Each
        # entry is a fitz word tuple (x0, y0, x1, y1, word, block_no,
        # line_no, word_no) -- page.get_text("words") already returns
        # words in natural reading order, so the selected subset stays
        # correctly ordered without re-sorting by geometry.
        self._selected_words = []  # (page_num, word) pairs -- Devin, 2026-07-26: cross-page selection
        self._selection_highlight_photos = []  # PhotoImage refs for the current selection overlay -- see _draw_text_selection_for_page
        # Slice 4 (Fable design review, 2026-07-25): two INDEPENDENT
        # axes, not one mode string -- Devin: "side by side option
        # (both can be turned on, checkbox in menu)", matching how
        # Adobe/Foxit's own "Two Page View" + "Scroll Continuously"
        # checkboxes actually combine. continuous_scroll=True (Devin:
        # "default to 'continuous scroll' please") is the "does the
        # canvas scroll through every row" axis; side_by_side is the
        # "how many pages per row" axis (cols=2 vs 1). self._layout
        # (layout.PageLayout) exists in ALL FOUR combinations now --
        # every coordinate-resolution call site generalizes to "does
        # self._layout exist" rather than a mode check.
        self.continuous_scroll = _saved["continuous_scroll"]
        self.side_by_side = _saved["side_by_side"]
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
        # BEFORE this render -- a real bug caught live: navigating to
        # page 2 in continuous mode synchronously clobbered
        # viewer.page_num right back to the OLD page via that stale
        # callback, before _go_to_page's own _scroll_to_page() call
        # ever ran. Suppressed during render() itself; real organic
        # scrolling (wheel/scrollbar-drag) is unaffected.
        self._suppress_scroll_sync = False
        self._drag_page = None  # page a click/drag started on, pinned for the whole gesture (continuous mode: a drag can visually cross page rects, but a redaction/annotation belongs to exactly one page)
        self._drag_anchor_pdf = None  # (x, y) in PDF space where the drag started -- text-flow selection's fixed start point, see _on_press/_on_drag
        self._pan_press_pos = None  # canvas (x, y) at ButtonPress-2 -- distinguishes a real drag-pan from a plain click (autoscroll toggle) at release
        self._autoscroll_active = False
        self._autoscroll_anchor = None  # (x, y), fixed for the session -- speed/direction come from cursor drift away from this point
        self._autoscroll_pos = None  # live cursor (x, y), updated by _on_canvas_motion
        self._autoscroll_indicator_id = None
        self._autoscroll_after_id = None
        # Slice 3 perf fix (Fable design review, 2026-07-25), after
        # Devin hit a real lockup on PageUp/PageDown: continuous mode
        # used to eager-render EVERY page on EVERY render() call. Now
        # windowed -- self._page_cache holds PhotoImages only for pages
        # near the viewport (it IS the keepalive; no separate list
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
        # Devin, 2026-07-25: "default TOC view = true." (now overridden
        # by a persisted value once the user has actually changed it --
        # 2026-07-26 -- default stays true for a first-ever launch.)
        self.toc_visible = tk.BooleanVar(value=_saved["toc_visible"])
        self.theme_name = tk.StringVar(value=theme.load_preference())
        # Read Aloud (TTS): app-wide, not per-tab -- reading one document
        # while switching tabs isn't a supported combination in v1.
        self.tts_voice = tk.StringVar(value=_saved["tts_voice"])
        self.tts_speed = tk.DoubleVar(value=_saved["tts_speed"])  # user-facing multiplier, not Piper's length_scale directly
        self.tts_player = TTSPlayer()
        # Position-indicator state (Devin, 2026-07-25: "is there a way
        # to tell what is the current voice/speed... a good application
        # for our green accent" + a real follow-along highlight) --
        # which page do_read_page() actually started reading, kept
        # fixed even if the user scrolls/navigates elsewhere while
        # listening. See _update_tts_highlight for the real estimation
        # method and its honest limitation.
        self._tts_reading_page = None
        self._tts_reading_page_num = None
        # The EXACT word list actually synthesized (Devin, 2026-07-26,
        # real bug: "read from here" starts at the top of the page, not
        # the point of my mouse) -- _update_tts_highlight used to always
        # re-derive the full page's own words from scratch, ignorant of
        # a "read from here" click trimming the START of what's actually
        # being read/spoken. See _update_tts_highlight's own docstring.
        self._tts_reading_words = []
        self._tts_chunk_sample_counts = []  # real per-sentence audio durations from tts.synthesize(), see _update_tts_highlight
        # Devin, 2026-07-25: "TTS: read entire document, not just
        # current page." True between do_read_document() and either
        # reaching the end of the document or an explicit Stop --
        # _poll_tts_playback_state uses _tts_was_playing to tell a
        # real natural end-of-audio apart from an explicit pause.
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
            # Session restore (Devin, 2026-07-26, extended same day to
            # include page position: "i want my Slate session to be
            # restored (document position)"). Missing/moved files are
            # skipped silently (same "a dead link is worse than no
            # entry" philosophy already used by recent.py) rather than
            # erroring on launch over a file that's since been deleted.
            # Each entry is normally {"path": ..., "page": N} now, but a
            # settings.json written by an earlier build of this feature
            # (same day, before page position existed) still has plain
            # path strings -- handled here rather than forcing a manual
            # file edit or a migration script for one dev's own local file.
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

        # Auto-check on launch (Devin, 2026-07-25: "auto-checks for
        # updates"). Delayed 2s so it never competes with initial
        # doc-load/render for the same event loop; silent unless
        # there's real news (see _check_for_updates's docstring).
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
        Windows actually reads for the taskbar/Alt-Tab icon. Devin,
        2026-07-25: "make the icon(s) official in the taskbar/
        titlebar." NOT live-verified against a real Windows box from
        here -- same "built against the documented mechanism, needs a
        real machine to fully confirm" caveat as
        _apply_native_titlebar_theme.
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
            # switch is a full cache bust, same cost as a zoom change
            # (Fable design review, 2026-07-25, Slice 3 perf consult).
            self._page_cache.invalidate_all()
            self.render()  # re-invert the currently-visible page immediately, not on next nav

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

    def _apply_native_titlebar_theme(self):
        """The window title bar itself is drawn by the OS, not Tk --
        genuinely an "outer" component no amount of widget.configure()
        can touch. Windows 10 (2004+)/11 support a real, documented DWM
        attribute for this (DWMWA_USE_IMMERSIVE_DARK_MODE = 20).
        Best-effort only: wrapped broadly because ctypes.windll doesn't
        exist at all off Windows, and older Windows builds don't
        support this attribute -- either way, failing soft just means
        the title bar stays whatever it already was, never a crash.
        NOT live-verified against a real Windows box (this dev
        environment is Linux/WSL2) -- same "built against the
        documented API, needs an actual machine to confirm" caveat as
        fontmatch.py's Windows registry path.
        """
        if platform.system() != "Windows":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
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

        Real platform constraint (theme.py's own docstring, not
        repeated in full here): tk.Menu dropdown popups are drawn by
        the native Win32 renderer on Windows and ignore these colors
        there -- harmless to set anyway, and correct on Linux/X11.
        """
        colors = theme.get_palette(self.theme_name.get())
        self.root.configure(bg=colors["bg"])
        self._paint_widget(self.root, colors)
        self._apply_native_titlebar_theme()

        style = ttk.Style()
        style.theme_use("clam")
        # tabstrip_bg, not plain bg -- the Notebook's own background is
        # the MIDDLE step of the menubar->tabstrip->toolbar cascade
        # (Devin, 2026-07-25: "make menu bar cascade down in color from
        # window bar down to tabs, to toolbar making it aesthetic").
        style.configure("TNotebook", background=colors["tabstrip_bg"], borderwidth=0)
        # Tab redesign (Devin, 2026-07-25, seeing it running live: "the
        # sepia... remove that from the tabs... come up with a better,
        # more creative solution"). No color block at all now, active
        # or inactive -- inactive = button_bg/muted_fg (a quiet card,
        # recedes into the chrome), active = bg/fg (the SAME tone as
        # the content area below it, so the active tab visually melts
        # into the page instead of sitting on top of it as a colored
        # block) -- distinguished from inactive purely by brightness
        # (bright fg text vs muted_fg), the way a lit panel reads
        # against darker ones on a manga page, not by a filled color.
        style.configure(
            "TNotebook.Tab", background=colors["button_bg"], foreground=colors["muted_fg"]
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", colors["bg"])],
            foreground=[("selected", colors["fg"])],
        )
        style.configure(
            "Treeview",
            background=colors["entry_bg"],
            foreground=colors["fg"],
            fieldbackground=colors["entry_bg"],
        )
        # Real bug caught live (Devin, 2026-07-25: "the highlight in
        # TOC is blue, i want that to be inkbone green") -- selected-
        # row color was never actually styled here at all; it was
        # riding ttk's own 'clam' theme built-in default (a blue-ish
        # highlight), completely independent of Slate's own palette,
        # this whole time. Now genuinely theme-driven via highlight_bg.
        style.map(
            "Treeview",
            background=[("selected", colors["highlight_bg"])],
            foreground=[("selected", colors["bg"])],
        )

        self._apply_chrome_theme(colors)

        if hasattr(self, "mode_label"):
            self._set_mode(self.mode)  # reassert redact's red badge over the generic pass

    def _apply_chrome_theme(self, colors):
        """The chrome CASCADE (Devin, 2026-07-25): "make menu bar
        cascade down in color from window bar down to tabs, to toolbar
        making it aesthetic," same rule for all 3 core families
        (Standard/Inkbone/Solarized) -- see theme.py's
        _with_chrome_cascade for the actual 3-step values (menubar_bg
        = bg, tabstrip_bg = midpoint, toolbar_bg = button_bg). This
        method applies menubar_bg/fg to the menubar and toolbar_bg/fg
        to the toolbar + scrollbars, overriding the generic bg/fg the
        recursive _paint_widget pass already applied to them as plain
        Frames/Labels/Buttons. tabstrip_bg is applied separately, via
        ttk.Style's "TNotebook" background above (a ttk widget, not
        part of this plain-Tk walk). Menu itself is native-rendered on
        Windows (same documented limitation as elsewhere in this
        file) -- setting it anyway is harmless and correct on Linux.
        """
        if hasattr(self, "menubar"):
            try:
                self.menubar.configure(bg=colors["menubar_bg"], fg=colors["menubar_fg"])
            except tk.TclError:
                pass
        if hasattr(self, "toolbar"):
            self._paint_chrome_subtree(self.toolbar, colors["toolbar_bg"], colors["toolbar_fg"])
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
        Dagaz (ᛞ) from TART's own rune palette (tart.h's "Runes" row) --
        replaces an earlier literal stacked-stones cairn (Devin,
        2026-07-25: "no more green turd cairn plz... one of the classic
        rune symbols that we have in Tart"). Dagaz's shape (two
        triangles meeting at a point) reads naturally as a resize
        handle, and its meaning -- dawn, breakthrough -- fits a blank
        page/new-document tool. Rendered in the same neutral chrome
        text color as the rest of the toolbar band, not a special
        accent -- minimal, not a mascot."""
        g = self._corner_grip
        g.configure(bg=colors["toolbar_bg"])
        g.delete("all")
        g.create_text(11, 11, text="ᛞ", font=("TkDefaultFont", 14),
                       fill=colors["toolbar_fg"], anchor="center")

    def _on_corner_grip_press(self, event):
        """Devin, 2026-07-25: "make the 'corner' hitbox bigger, i often
        just want the corner to resize both H and V" -- standard OS
        bottom-right window-resize convention, hand-rolled because the
        actual hitbox needs to be bigger than a bare ttk.Sizegrip's
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
        """Real bug Devin caught live, 2026-07-25: "the initial
        bottomright resize moves the window's top left." Root cause: a
        size-only geometry string ("WxH", no "+x+y") occasionally gets
        re-anchored by the window manager instead of preserving the
        existing top-left corner, on the very first resize call after
        the window's position was last set with its own separate
        geometry("+x+y") call (see main()'s startup centering) -- Tk
        has no guarantee the WM keeps remembering a position it wasn't
        just told. Fix: always pass position explicitly, pinned to
        what it was when the drag started, so the WM never has to
        guess or "remember" anything."""
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
        else:
            cls = widget.winfo_class()
            try:
                if cls in ("Toplevel", "Tk"):
                    widget.configure(bg=colors["bg"])  # no -fg option on these
                elif cls == "Frame":
                    # Real bug caught live (Devin's screenshot,
                    # 2026-07-25 -- the home screen never themed
                    # itself): Frame has NO -fg option at all (only
                    # Label does), so the original combined
                    # `configure(bg=..., fg=...)` here threw
                    # "unknown option -fg" for every single Frame in
                    # the app, silently swallowed by the blanket
                    # except TclError below -- meaning bg was NEVER
                    # actually applied to any plain Frame via this
                    # generic pass, ever, app-wide. Masked everywhere
                    # else by a separate override (toolbar/menubar's
                    # own _apply_chrome_theme, canvas's own Canvas-
                    # class branch below); the home screen was just
                    # the first place with no such override to hide it.
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
                    # First real use of bare (non-menu) Checkbutton/
                    # Radiobutton widgets in the app -- the Settings
                    # dialog's menu-equivalent checkboxes/radios are Menu
                    # entries (a different code path, handled by the
                    # "Menu" branch below), never a standalone widget
                    # class, so this branch never existed until now.
                    # selectcolor (the checked-indicator color) is left
                    # alone -- callers already pass their own green
                    # accent for it at construction time.
                    widget.configure(
                        bg=colors["bg"], fg=colors["fg"], activebackground=colors["bg"],
                        activeforeground=colors["fg"],
                    )
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
        # Devin, 2026-07-25, real screenshot: "if this is inkbone dark,
        # i cannot see the menu checkboxes" -- see RADIO_SELECT_COLOR's
        # own module-level comment for the full story (now shared with
        # the Settings dialog's standalone radios/checkboxes too, which
        # had the same bug independently). Fixed value, not re-themed
        # live on theme switch (the native Win32 menu popup itself is
        # already a documented can't-fully-control surface, see
        # theme.py's own docstring).
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
        # Slice 4 (Fable design review, 2026-07-25): independent
        # checkboxes, not mutually-exclusive radio options -- Devin:
        # "side by side option (both can be turned on, checkbox in
        # menu)", matching Adobe/Foxit's own "Two Page View" + "Scroll
        # Continuously" combination.
        self.continuous_scroll_var = tk.BooleanVar(value=self.continuous_scroll)
        self.side_by_side_var = tk.BooleanVar(value=self.side_by_side)
        # Book View (Devin, 2026-07-29): Sumatra-style single toggle that
        # rolls up Continuous Scroll + Side by Side + Fit Width into one
        # F8 press, instead of setting both checkboxes by hand every time.
        # Derived state, not a third independent axis -- stays in sync
        # with the two underlying checkboxes in both directions (toggling
        # either individual box updates this one's displayed check too,
        # see _set_view_mode). Real gap named, not faked: a "centered"
        # page alignment was asked for as part of "book view" too, but
        # that's one of the 3 Slate notes still queued (not built yet) --
        # this toggle only does what's actually real today (scroll +
        # side-by-side + fit-width), not a centered layout.
        self.book_view_var = tk.BooleanVar(value=self.continuous_scroll and self.side_by_side)
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
        # Colorize opt-OUT-by-default (Devin, 2026-07-26, flipped same day
        # after actually hitting it): _colorize_for_theme flattens every
        # page to the theme's fg/bg pair, which destroys real color
        # content (a categorical diagram, a photo) -- real example hit
        # live the same day, a bake-off comparison diagram with real
        # blue/orange bars. Default is now off (self.colorize_pages=False);
        # a prose-only reader who wants the old tinted-to-match-theme look
        # can still opt back in via this checkbox.
        self.colorize_pages_var = tk.BooleanVar(value=self.colorize_pages)
        viewm.add_checkbutton(
            label="Colorize pages to theme", variable=self.colorize_pages_var,
            command=self._on_colorize_toggle, selectcolor=radio_select_color,
        )
        # Crop to Content (Devin, 2026-07-29): opt-in same as Colorize
        # above -- a display-altering feature, default off so it doesn't
        # surprise an existing workflow.
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

        readm = tk.Menu(menubar, tearoff=0)
        voicem = tk.Menu(readm, tearoff=0)
        for voice_id, info in tts.VOICES.items():
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
        readm.add_command(label="Read this page", command=self.do_read_page)
        readm.add_command(label="Read entire document", command=self.do_read_document)
        readm.add_command(label="Pause / Resume", command=self.do_tts_pause_resume)
        readm.add_command(label="Stop", command=self.do_tts_stop)
        menubar.add_cascade(label="Read Aloud", menu=readm)

        # Check for Updates lives on the About dialog now, not a
        # separate menu item (Devin, 2026-07-25: "having updates in
        # about means the menu option can be removed").
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About Slate...", command=self._show_about)
        menubar.add_cascade(label="Help", menu=helpm)

        self.root.config(menu=menubar)

    def _check_for_updates(self, silent_if_current: bool):
        """Real network call, always on a background thread -- same
        thread-safety pattern already established for TTS synthesis/
        voice downloads (never touch Tk widgets off the main thread;
        poll a plain dict via root.after()). silent_if_current=True is
        the startup auto-check (Devin, 2026-07-25: "auto-checks for
        updates") -- stays quiet unless there's real news, so it never
        nags on every launch; the menu-triggered manual check always
        reports something, even "up to date" or a real error."""
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
        """F2 (Devin, 2026-07-25: "is there an easier way for me to
        change the theme please? f2 command palette or something?").
        v1 scope is theme-switching, but built as a real (label,
        action) list + live filter rather than a theme-only hardcoded
        dialog -- the smallest real command palette, not a one-off,
        so it's a natural extension point later rather than a dead
        end. Escape/click-away cancels; Enter or a click applies the
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
        colors = theme.get_palette(self.theme_name.get())
        top = tk.Toplevel(self.root)
        top.title("About Slate")
        top.resizable(False, False)

        header = tk.Frame(top)
        header.pack(padx=24, pady=(18, 6), anchor="w")
        if getattr(self, "_icon_img", None) is not None:
            # Same subsample(4,4) reuse-not-reload trick as the home
            # screen's own logo -- Devin, 2026-07-25: "along with the
            # icon in a good spot as well, i love the slate icon."
            logo = self._icon_img.subsample(4, 4)
            self._about_logo_img = logo  # keep a reference, same gotcha as _tk_img/_home_logo_img
            tk.Label(header, image=logo).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            header, text=f"Slate {version.VERSION}", font=("TkDefaultFont", 14, "bold")
        ).pack(side=tk.LEFT)

        # Permanent green accent (Devin, 2026-07-25: "could we add a
        # clever accent of green on the 'about' as well?" then "please
        # add a permanent, clever hint of inkbone green on the about
        # page please"). FIXED hex, not colors["highlight_bg"] -- that
        # field is theme-variable (Solarized's real accent is blue, on
        # purpose, per the same-day official-palette review), but this
        # mark is meant to read as Slate's own house color on the
        # About page specifically, regardless of which theme is active.
        accent_bar = tk.Frame(top, bg="#62a945", height=2)
        accent_bar.pack(fill=tk.X, padx=24, pady=(0, 10))
        tk.Label(
            top, text=version.SUMMARY, wraplength=360, justify="left"
        ).pack(padx=24, pady=(0, 12))
        author_label = tk.Label(top, text=f"© 2026 {version.AUTHOR}", fg="gray40")
        author_label.slate_muted = True
        author_label.pack(padx=24, pady=(0, 18))
        button_row = tk.Frame(top)
        button_row.pack(pady=(0, 14))
        # Check for Updates lives here now, not a separate Help menu
        # item (Devin, 2026-07-25). Spacing tuned live twice same day:
        # 8px read as "too close," 24px read as "a gap" -- 10px landed.
        tk.Button(
            button_row, text="Check for Updates...",
            command=lambda: self._check_for_updates(silent_if_current=False),
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(button_row, text="Close", command=top.destroy).pack(side=tk.LEFT)
        self._paint_widget(top, colors)
        # Real bug caught by this dialog's own test: the generic
        # _paint_widget walk above recolors EVERY Frame to the theme's
        # bg, including accent_bar -- it doesn't know this one is
        # meant to stay fixed. Re-assert the permanent green after the
        # generic pass, not before.
        accent_bar.configure(bg="#62a945")

        # Center over the main window, not the top-left corner (Devin,
        # 2026-07-25) -- real geometry only exists after the widgets
        # above are actually laid out, hence update_idletasks() first.
        top.update_idletasks()
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        root_w, root_h = self.root.winfo_width(), self.root.winfo_height()
        dlg_w, dlg_h = top.winfo_width(), top.winfo_height()
        x = root_x + (root_w - dlg_w) // 2
        y = root_y + (root_h - dlg_h) // 2
        top.geometry(f"+{x}+{y}")

    def _show_settings(self):
        """Settings dialog (Devin, 2026-07-26 handoff): a single place to
        see and change every persisted preference, modeled on
        _show_about's own Toplevel/accent-bar/centering pattern. Every
        control here binds to the SAME Tk variable and calls the SAME
        handler the corresponding menu item already uses (continuous_scroll_var
        -> _set_view_mode, colorize_pages_var -> _on_colorize_toggle,
        tts_voice/tts_speed -> their existing _on_..._changed handlers)
        -- one source of truth, so this dialog and the menus can never
        drift out of sync with each other. This dialog is a second
        place to reach settings that already persist via those handlers,
        not a second mechanism that persists them independently."""
        colors = theme.get_palette(self.theme_name.get())
        top = tk.Toplevel(self.root)
        top.title("Settings")
        top.resizable(False, False)

        header = tk.Frame(top)
        header.pack(padx=24, pady=(18, 6), anchor="w")
        tk.Label(
            header, text="Settings", font=("TkDefaultFont", 14, "bold")
        ).pack(side=tk.LEFT)
        accent_bar = tk.Frame(top, bg="#62a945", height=2)
        accent_bar.pack(fill=tk.X, padx=24, pady=(0, 10))

        # -- Theme -- same THEME_LABELS/self.theme_name/_on_theme_changed
        # the View>Theme submenu already uses, not a second theme picker.
        # _on_theme_changed_and_repaint (below) runs the normal handler
        # (repaints the main window, saves the preference, invalidates the
        # page cache) THEN repaints this still-open dialog too, same
        # _paint_widget + accent-bar-reassert pattern this function already
        # runs once at the bottom for the initial paint -- Devin, 2026-07-26:
        # "the settings page should fully match the theme," not just at
        # open time.
        def _on_theme_changed_and_repaint():
            self._on_theme_changed()
            self._paint_widget(top, theme.get_palette(self.theme_name.get()))
            accent_bar.configure(bg="#62a945")

        theme_frame = tk.LabelFrame(top, text="Theme")
        theme_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
        for label, name in theme.THEME_LABELS.items():
            tk.Radiobutton(
                theme_frame, text=label, variable=self.theme_name, value=name,
                command=_on_theme_changed_and_repaint, selectcolor=RADIO_SELECT_COLOR,
            ).pack(anchor="w", padx=10, pady=1)

        # -- View --
        view_frame = tk.LabelFrame(top, text="View")
        view_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
        tk.Checkbutton(
            view_frame, text="Continuous Scroll", variable=self.continuous_scroll_var,
            command=self._set_view_mode, selectcolor=RADIO_SELECT_COLOR,
        ).pack(anchor="w", padx=10, pady=(6, 2))
        tk.Checkbutton(
            view_frame, text="Side by Side", variable=self.side_by_side_var,
            command=self._set_view_mode, selectcolor=RADIO_SELECT_COLOR,
        ).pack(anchor="w", padx=10, pady=2)
        tk.Checkbutton(
            view_frame, text="Book View (F8)", variable=self.book_view_var,
            command=self._toggle_book_view, selectcolor=RADIO_SELECT_COLOR,
        ).pack(anchor="w", padx=10, pady=2)
        tk.Checkbutton(
            view_frame, text="Colorize pages to theme", variable=self.colorize_pages_var,
            command=self._on_colorize_toggle, selectcolor=RADIO_SELECT_COLOR,
        ).pack(anchor="w", padx=10, pady=2)
        tk.Checkbutton(
            view_frame, text="Crop to Content", variable=self.crop_to_content_var,
            command=self._on_crop_toggle, selectcolor=RADIO_SELECT_COLOR,
        ).pack(anchor="w", padx=10, pady=2)
        tk.Checkbutton(
            view_frame, text="Show Table of Contents", variable=self.toc_visible,
            command=self._toggle_toc_panel, selectcolor=RADIO_SELECT_COLOR,
        ).pack(anchor="w", padx=10, pady=(2, 6))

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

        # -- Read Aloud --
        tts_frame = tk.LabelFrame(top, text="Read Aloud")
        tts_frame.pack(fill=tk.X, padx=24, pady=(0, 10))
        tk.Label(tts_frame, text="Voice:").pack(anchor="w", padx=10, pady=(6, 0))
        voice_row = tk.Frame(tts_frame)
        voice_row.pack(fill=tk.X, padx=10)
        for voice_id, info in tts.VOICES.items():
            tk.Radiobutton(
                voice_row, text=info["label"], variable=self.tts_voice, value=voice_id,
                command=self._on_tts_voice_changed, selectcolor=RADIO_SELECT_COLOR,
            ).pack(anchor="w")
        tk.Label(tts_frame, text="Speed:").pack(anchor="w", padx=10, pady=(6, 0))
        speed_row = tk.Frame(tts_frame)
        speed_row.pack(fill=tk.X, padx=10, pady=(0, 6))
        for speed in (0.75, 1.0, 1.25, 1.5, 2.0):
            tk.Radiobutton(
                speed_row, text=f"{speed}x", variable=self.tts_speed, value=speed,
                command=self._on_tts_speed_changed, selectcolor=RADIO_SELECT_COLOR,
            ).pack(side=tk.LEFT, padx=(0, 8))

        btn_row = tk.Frame(top)
        btn_row.pack(pady=(0, 16))
        tk.Button(btn_row, text="About Slate...", command=self._show_about).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Close", command=top.destroy).pack(side=tk.LEFT)

        self._paint_widget(top, colors)
        accent_bar.configure(bg="#62a945")  # same re-assert-after-paint fix as _show_about

        top.update_idletasks()
        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        root_w, root_h = self.root.winfo_width(), self.root.winfo_height()
        dlg_w, dlg_h = top.winfo_width(), top.winfo_height()
        x = root_x + (root_w - dlg_w) // 2
        y = root_y + (root_h - dlg_h) // 2
        top.geometry(f"+{x}+{y}")

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
        # it on an ebook format crashes with "Illegal PDF header", a real
        # bug caught live writing this slice's own epub test. Signing is
        # itself a PDF-only menu item (gated off elsewhere), so a non-PDF
        # document is never "signed" by definition.
        # self.path is the ORIGINAL path (tab convention, see
        # _open_document) even for a tab whose actual content came
        # from a converted temp PDF (HTML/image opens, convert.
        # path_to_pdf). sign.is_signed() opens self.path itself via
        # pyhanko -- for an .html/.png source that's not a PDF at all
        # ("Illegal PDF header"), a real crash caught live 2026-07-25
        # wiring the HTML-open feature. Guard on the path's own
        # extension, not just self.doc.is_pdf (which reflects the
        # loaded-in-memory format, already true for a converted HTML
        # doc, and would NOT have caught this).
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
        """Devin, 2026-07-26: "please use better cursors" -- prompted
        right after adding middle-click-drag pan (_on_pan_press/
        _on_pan_release below swap to a "fleur" move cursor for the
        duration of an active pan, then restore whatever this
        returns). A distinct cursor per interaction SHAPE, not
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
        """Devin, 2026-07-26: "extend the middle click pan to a middle
        click 'scroll'" -- the other real middle-button convention,
        browser-style click-to-autoscroll, alongside the drag-to-pan
        already here. Both share ButtonPress-2; which one you get is
        decided at RELEASE (_on_pan_release) by whether the mouse
        actually moved before letting go -- a real drag pans (already
        happened live via scan_dragto during the drag itself, this
        press just arms it), a plain click starts/stops autoscroll."""
        if self._autoscroll_active:
            # A click while autoscroll is already running is the
            # cancel gesture (browser convention) -- stop here, don't
            # also arm scan_mark for what would read as a real pan.
            self._stop_autoscroll()
            return
        self._pan_press_pos = (event.x, event.y)
        # Pan disabled (see the commented-out B2-Motion binding above) --
        # scan_mark/fleur cursor commented out to match; _pan_press_pos
        # is still needed below to detect click-vs-drag for autoscroll.
        # self.canvas.scan_mark(event.x, event.y)
        # self.canvas.config(cursor="fleur")

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
        # Directional cursor (Devin, 2026-07-26: "change the 'scroll'
        # cursor to an up/down arrow or left/right arrow for those
        # autoscrolling times") -- reflects whichever axis is actually
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
        if mode == "redact":
            # Real safety nudge, not just cosmetics: redact is the one
            # mode where a mis-drag has irreversible consequences
            # (DESIGN.md's redaction section) -- the mode indicator
            # should not look identical to every harmless mode.
            self.mode_label.config(
                text=f"mode: {mode}", fg="white", bg="#c0392b", padx=6
            )
        else:
            self.mode_label.config(
                text=f"mode: {mode}", fg="blue", bg=self._mode_label_default_bg, padx=0
            )

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

        header = tk.Frame(self.home_frame)
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
            title_box, text=f"Slate {version.VERSION}", font=("TkDefaultFont", 20, "bold")
        ).pack(anchor="w")
        tagline = tk.Label(
            title_box, text=version.SUMMARY, wraplength=460, justify="left", fg="gray30"
        )
        tagline.slate_muted = True  # theme walker keeps this dimmer than normal text
        tagline.pack(anchor="w", pady=(4, 0))

        tk.Button(self.home_frame, text="Open...", command=self.open_file).pack(
            anchor="w", pady=(16, 16)
        )

        tk.Label(self.home_frame, text="Recently viewed", font=("TkDefaultFont", 12, "bold")).pack(
            anchor="w"
        )
        entries = recent.get_recent()
        if not entries:
            no_files_label = tk.Label(self.home_frame, text="No recently viewed files", fg="gray40")
            no_files_label.slate_muted = True
            no_files_label.pack(anchor="w", pady=6)
        else:
            self._recent_entries = entries
            self._recent_listbox = tk.Listbox(
                self.home_frame, width=90, height=min(10, len(entries))
            )
            for e in entries:
                name = os.path.basename(e["path"])
                parent = os.path.dirname(e["path"])
                self._recent_listbox.insert("end", f"{name}   —   {parent}")
            self._recent_listbox.pack(fill=tk.BOTH, expand=True, pady=6)
            self._recent_listbox.bind("<Double-Button-1>", self._open_recent_selected)
            self._recent_listbox.bind("<Return>", self._open_recent_selected)
            # Delete/Backspace on the selected row + a right-click "Remove"
            # (Devin, 2026-07-26: "delete items from the recently opened
            # list") -- two paths to the same removal, mouse-only still
            # works while Start's own search box is fighting keyboard
            # input. Right-click selects the row under the cursor FIRST
            # (a Listbox doesn't do this by default), so the removal
            # always acts on what was actually clicked, not whatever the
            # previous selection happened to be.
            self._recent_listbox.bind("<Delete>", self._remove_recent_selected)
            self._recent_listbox.bind("<BackSpace>", self._remove_recent_selected)
            self._recent_listbox.bind("<Button-3>", self._show_recent_context_menu)

        # Real bug, caught live (Devin's screenshot, 2026-07-25): the
        # home screen never themed itself at all -- __init__ calls
        # _apply_theme() BEFORE _show_home_screen() ever builds
        # home_frame (nothing to paint yet), and the tab-close-back-to-
        # -home path (_close_tab_by_index) has the same gap, so the
        # home screen always rendered plain default Tk light styling
        # regardless of the active theme, no matter which of the two
        # call sites reached it. Self-contained fix here rather than
        # reordering __init__ -- covers both paths at once.
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
        """Right-click on a recent-files row -- Devin, 2026-07-26: works
        mouse-only, no keyboard needed (relevant right now: Start's own
        search box is fighting keyboard input on his machine). Selects
        the row under the cursor first, since a Listbox doesn't do that
        on a right-click by itself -- without this, a right-click far
        from the current selection would remove the WRONG entry."""
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
        # Left-click close (Devin, 2026-07-26: "'x' on last document tab
        # doesn't close it") -- see _on_tab_strip_left_click's own
        # docstring for the real bbox()-is-broken finding this works
        # around, and why the LAST tab specifically needed it.
        self.tab_strip.bind("<Button-1>", self._on_tab_strip_left_click)

        # 3-column grid, not one flat pack() row -- the only reliable
        # way to get a toolbar element TRULY centered in Tk regardless
        # of how wide the left/right clusters are. Equal weight on
        # columns 0 and 2 makes them absorb any extra window width
        # equally, which keeps column 1 (the page indicator) sitting
        # mathematically centered. Devin, 2026-07-25: "move the current
        # page / total page UI element to the top-center... mimic
        # Foxit's UI as much as possible" -- Foxit/Acrobat-convention
        # editable page-number box + "of N" (type a number, Enter
        # jumps there), not just relocated static text.
        toolbar = self.toolbar = tk.Frame(self.body_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_columnconfigure(2, weight=1)

        toolbar_left = tk.Frame(toolbar)
        toolbar_left.grid(row=0, column=0, sticky="w")
        tk.Button(toolbar_left, text="< Prev", command=self.prev).pack(side=tk.LEFT)
        tk.Button(toolbar_left, text="Next >", command=self.next).pack(side=tk.LEFT)
        tk.Button(toolbar_left, text="Zoom -", command=self.zoom_out).pack(side=tk.LEFT)
        tk.Button(toolbar_left, text="Zoom +", command=self.zoom_in).pack(side=tk.LEFT)
        tk.Button(toolbar_left, text="Fit Width", command=self.fit_width).pack(side=tk.LEFT)
        self.mode_label = tk.Label(toolbar_left, text="mode: view", fg="blue")
        self.mode_label.pack(side=tk.LEFT, padx=12)
        self._mode_label_default_bg = self.mode_label.cget("bg")

        toolbar_center = tk.Frame(toolbar)
        toolbar_center.grid(row=0, column=1)
        # Small prev/next glyph buttons flank the page box (Devin,
        # 2026-07-25: "easier to change pages, not just text box (which
        # i still like the input to go straight [to] a page number)")
        # -- the typed-number-jumps-straight-there behavior is
        # untouched, this is purely an ADDITIONAL click path for the
        # common "just go one page" case.
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
        # Read Aloud quick-access controls (Devin, 2026-07-25: "easier
        # 'audio readback' controls, preferably also available on the
        # main toolbar" -- previously only reachable via the Read
        # Aloud menu). Two buttons: one smart play/pause/resume toggle
        # (do_tts_toggle_play decides which action makes sense for the
        # current state) plus a stop, same real actions the menu
        # already exposes, not a separate mechanism.
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
        # mechanism, rather than hand-rolling drag math (Devin's ask,
        # 2026-07-25: "TOC should be drag resizeable too please").
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

        # Real gap Devin caught, 2026-07-25 ("and a h/v scrollbar"): a
        # page zoomed larger than the window had NO way to see the
        # rest of it -- the canvas had no scrollregion/scrollbars at
        # all, just silent clipping. canvas_frame holds canvas + both
        # scrollbars together (grid, not pack -- the standard Tk
        # 2x2 canvas/scrollbar layout) so the PAIR can be added to the
        # PanedWindow as one pane.
        canvas_frame = tk.Frame(content)
        # highlightthickness=0/bd=0: Tk's default 1px focus-highlight
        # border was silently offsetting every canvasx()/canvasy()
        # click-to-pdf coordinate conversion by 1px -- invisible before
        # render() forced update_idletasks() (real geometry realization
        # made the border inset apply consistently instead of by luck).
        self.canvas = tk.Canvas(canvas_frame, bg="gray80", highlightthickness=0, bd=0)
        self._vscroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self._hscroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        # yscrollcommand SHOULD fire on every y-view change regardless
        # of cause, but confirmed live (this dev box's headless Xvfb)
        # that a plain yview_moveto()/scrollbar-drag doesn't reliably
        # trigger it, even after root.update() -- kept as a belt-and-
        # suspenders hook, but continuous mode's page-number sync does
        # NOT depend on it alone (see the explicit _sync_page_num_
        # from_scroll() calls in the wheel handlers and the scrollbar-
        # drag bindings just below).
        self.canvas.configure(yscrollcommand=self._on_canvas_yscroll, xscrollcommand=self._hscroll.set)
        self._vscroll.bind("<B1-Motion>", self._sync_page_num_from_scroll)
        self._vscroll.bind("<ButtonRelease-1>", self._sync_page_num_from_scroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")
        self._hscroll.grid(row=1, column=0, sticky="ew")
        # Devin, 2026-07-25: "add something creative in the bottom
        # right corner where the scrollbars collide... in the spirit
        # of Cairn" (later swapped for a TART rune, see
        # _draw_corner_grip) + "make the 'corner' hitbox bigger, i
        # often just want the corner to resize both H and V" -- a real
        # drag-to-resize grip (standard OS bottom-right window resize
        # convention) with a bigger-than-default hitbox (22px vs a
        # plain scrollbar's ~17px) instead of the usual bare diagonal
        # hatch.
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
        # Devin, 2026-07-25: "if the horizontal size reaches 'side by
        # side' size, Slate automatically toggles it" -- real width-
        # based auto layout on top of the manual checkbox, not a
        # replacement for it (see _on_canvas_frame_configure).
        canvas_frame.bind("<Configure>", self._on_canvas_frame_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Middle-click-drag-to-pan DISABLED (Devin, 2026-07-26): any tiny
        # hand tremor during a middle-click-to-autoscroll gesture was
        # live-panning the page via this B2-Motion binding before the
        # click/drag distinction below even got checked at release --
        # "defaults to pan so quickly when I try to scroll right after."
        # Commented out, not deleted, in case pan is wanted back later --
        # to re-enable, uncomment the B2-Motion line below (it was the
        # only thing actually doing the panning; ButtonPress-2/
        # ButtonRelease-2 stay bound because they're also what runs
        # click-to-autoscroll, below).
        # Right-click = context menu (Devin, 2026-07-26: "a good right-
        # click menu"), view mode only -- see _show_canvas_context_menu's
        # own docstring for why and what's in it. "Read from here"
        # started as this binding's own instant action earlier the same
        # day; folded into the menu once a real menu existed, same
        # click, one more step.
        self.canvas.bind("<Button-3>", self._show_canvas_context_menu)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        # self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<Motion>", self._on_canvas_motion)

        # All routed through the same guarded _kb_prev_page/_kb_next_page
        # as j/k below -- a real pre-existing gap fixed while adding
        # these: Left/Right/Up/Down/PageUp/PageDown were previously
        # bound directly to prev()/next() with NO "am I typing
        # somewhere" guard at all, so pressing e.g. Left to move the
        # text cursor while typing in the Find box would ALSO flip a
        # page underneath it.
        self.root.bind("<Left>", self._kb_prev_page)
        self.root.bind("<Right>", self._kb_next_page)
        self.root.bind("<Up>", self._kb_prev_page)
        self.root.bind("<Down>", self._kb_next_page)
        self.root.bind("<Prior>", self._kb_prev_page)  # Page Up
        self.root.bind("<Next>", self._kb_next_page)  # Page Down
        # Home/End = first/last page (Devin, 2026-07-26: "home/end
        # aren't work[ing]") -- same handlers vim-style g/G already use
        # below; Home/End is the more universal Adobe/Foxit/Sumatra
        # convention, this was just never bound to it.
        self.root.bind("<Home>", self._kb_first_page)
        self.root.bind("<End>", self._kb_last_page)
        # Mouse wheel: Windows/Mac deliver <MouseWheel> with a signed
        # event.delta; X11/Linux (this dev environment) instead sends
        # discrete Button-4 (up) / Button-5 (down) click events with no
        # delta at all -- both bound so this is actually testable here,
        # not just assumed to work on the real deployment target. Both
        # now route through _wheel_up/_wheel_down (Fable design review,
        # 2026-07-25) -- previously Button-4/5 bypassed _on_mouse_wheel
        # entirely and called page-nav directly, a real X11/Windows
        # parity gap that only happened to be invisible because both
        # paths did the exact same unconditional thing.
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", self._wheel_up)
        self.canvas.bind("<Button-5>", self._wheel_down)
        # Ctrl+scroll = zoom (Devin, 2026-07-25), same platform split as
        # plain wheel above -- Tk's compound event names route the
        # Control-modified wheel to a separate binding automatically,
        # no manual event.state check needed.
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mouse_wheel)
        self.canvas.bind("<Control-Button-4>", lambda e: self.zoom_in())
        self.canvas.bind("<Control-Button-5>", lambda e: self.zoom_out())
        # Shift+scroll = horizontal scroll (Devin, 2026-07-26), same
        # platform split as Ctrl+scroll above.
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

        # CUA keybinds (Devin, 2026-07-25: "ctrl+w close tab (and other
        # CUA keybinds)") -- the standard Windows/Mac shortcut set,
        # matching menu accelerators added alongside these.
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
        # Real bug caught live: these widgets are built lazily, on first
        # document open -- _apply_theme() only ran once already, in
        # __init__, BEFORE any of them existed (their constructors'
        # hardcoded defaults, e.g. the canvas's bg="gray80", would
        # otherwise silently stick forever for an app launched directly
        # with a path, since nothing re-themes them until the user
        # manually re-picks a theme later).
        self._apply_theme()
        # Devin, 2026-07-25: "default TOC view = true" -- the BooleanVar
        # itself defaults True (__init__), but nothing actually added
        # the panel to the PanedWindow until now; _toggle_toc_panel
        # needs toc_frame/_canvas_frame, both real only once this
        # method has run this far.
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
        # Checkpoint the new position (Devin, 2026-07-26: restore
        # document position, not just which files were open). Plain
        # scrolling in continuous mode also moves page_num (see
        # _sync_page_num_from_scroll) but isn't checkpointed here on
        # purpose -- that fires on every scroll tick, and writing
        # settings.json that often is real, needless I/O; window close
        # (main()'s _on_close) does one final save covering wherever
        # scrolling actually left things, so a clean quit is never
        # stale even though mid-session scroll positions aren't
        # continuously persisted.
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
        continuous mode was entered -- Devin will notice immediately
        if this is missing (small, but real UX). Also the one real
        trigger point for _shift_window (Slice 3 perf fix) -- every
        organic scroll cause (wheel, scrollbar drag, yscrollcommand)
        already funnels through here, so windowing piggybacks on the
        same hook rather than needing its own."""
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
        """Devin, 2026-07-25: Page Layout submenu (View menu) --
        Continuous Scroll and Side by Side are independent checkboxes
        (Slice 4, Fable design review), not mutually-exclusive radio
        options."""
        self.continuous_scroll = self.continuous_scroll_var.get()
        self.side_by_side = self.side_by_side_var.get()
        settings.save({"continuous_scroll": self.continuous_scroll, "side_by_side": self.side_by_side})
        # Keep Book View's own checkbox honest even when the user toggles
        # the two underlying boxes individually rather than via F8/the
        # Book View item -- it should only show checked when BOTH
        # underlying axes actually agree, never a stale/independent guess.
        self.book_view_var.set(self.continuous_scroll and self.side_by_side)
        if self.viewer is None:
            return
        self._selected_words = []
        self.render()
        if self.continuous_scroll:
            self._scroll_to_page(self.viewer.page_num)
        else:
            self._reset_scroll()

    def _toggle_book_view(self):
        """Devin, 2026-07-29: "roll that up into Book View" -- one
        combined preset (Sumatra-naming) instead of setting Continuous
        Scroll + Side by Side by hand every time. Reads book_view_var's
        OWN new value (already flipped by Tk before this command fires,
        same as any checkbutton) and pushes that value onto both real
        axes, then reuses _set_view_mode's existing save/render/scroll
        path -- no duplicated logic. Fit Width included (Devin: "zoom to
        fit"); a centered alignment was also asked for but isn't real
        yet (queued Slate note, not this toggle's job to fake it)."""
        want = self.book_view_var.get()
        self.continuous_scroll_var.set(want)
        self.side_by_side_var.set(want)
        self._set_view_mode()
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

    def _on_canvas_frame_configure(self, event=None):
        """Devin, 2026-07-25: "if the horizontal size reaches 'side by
        side' size, Slate automatically toggles it." <Configure> fires
        continuously during a live drag-resize (and once per render()'s
        own canvas resize) -- debounced via after_cancel/after so the
        real width check only runs once resizing actually settles,
        not on every intermediate pixel."""
        if self._autolayout_after_id is not None:
            self.root.after_cancel(self._autolayout_after_id)
        self._autolayout_after_id = self.root.after(150, self._apply_width_based_side_by_side)

    def _apply_width_based_side_by_side(self):
        """Real width threshold, not a guess: a two-page spread at the
        CURRENT zoom needs 2 * (widest page's width) + one inter-page
        gap. continuous_scroll is never touched here (Devin, same
        thread: "continuous scroll stays a default") -- only the
        side_by_side axis auto-follows width. Always follows (no
        separate "did the user manually override this" tracking) --
        Devin's own call: "simplest: always auto-follow... unless
        Devin says otherwise once he sees it live." Reuses
        side_by_side_var + _set_view_mode so the View menu's checkbox
        stays visually in sync with whatever this decided."""
        self._autolayout_after_id = None
        if self.viewer is None or self.doc is None:
            return
        available_w = self._canvas_frame.winfo_width()
        page_w = self.doc[0].rect.width * self.viewer.zoom
        gap = self._layout.gap if self._layout is not None else 8
        should_be_side_by_side = available_w >= (2 * page_w + gap)
        if should_be_side_by_side != self.side_by_side_var.get():
            self.side_by_side_var.set(should_be_side_by_side)
            self._set_view_mode()

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
        the find box (or any other entry) doesn't also trigger a jump.
        The find box's own <Return> binding calls _find_next directly,
        unguarded, since Enter there is always a deliberate search."""
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
        so a crash or a hard kill (not just a clean Quit) still leaves
        an accurate session to restore -- same "resumable by
        construction" reasoning as recent.py's own self-healing list.

        Also called on every page turn (_go_to_page, Devin, 2026-07-26:
        "i want my Slate session to be restored (document position)")
        so the saved position is never stale -- open/close alone would
        only capture whatever page a tab happened to be on at the LAST
        add/remove, not wherever it was actually left. t.viewer is the
        real, live Viewer object for that tab (Tab.__init__ keeps it,
        tab.py's own docstring), the same object self.viewer points at
        while that tab is active -- so t.viewer.page_num is always
        current, no extra sync needed even for background tabs."""
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
        # Persisted zoom (Devin, 2026-07-26 handoff): a user-chosen zoom
        # carries across documents/launches instead of every new
        # document silently reverting to Viewer.DEFAULT_ZOOM. None means
        # "never explicitly set yet" (a first-ever launch, or zoom never
        # touched) -- leaves the class's own default alone in that case.
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
        the next idle-loop pass, not synchronously -- real bug hit live
        writing this feature's own tests: app.doc was still None right
        after _open_document() returned. Calling the handler directly
        here makes tab-loading synchronous and testable; the bound
        virtual event (real interactive tab clicks) still also fires
        afterward, which just reloads the same already-active tab --
        idempotent, harmless."""
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
        """Ctrl+Tab/Ctrl+Shift+Tab (Devin, 2026-07-25: CUA keybinds).
        Wraps around at either end, same convention as browser tabs."""
        tabs = self.tab_strip.tabs()
        if len(tabs) < 2:
            return
        current = self.tab_strip.index(self.tab_strip.select())
        self.tab_strip.select(tabs[(current + direction) % len(tabs)])

    def _on_tab_strip_click(self, event):
        """Middle-click closes a tab (same convention as Chrome/Firefox).
        Real finding while building this: ttk.Notebook.bbox() returns
        (0,0,0,0) for every tab (confirmed across 'default'/'clam' AND,
        2026-07-26, the real Windows 'vista' theme too -- not a
        headless-only quirk) despite the widget being mapped with
        real, non-zero dimensions -- breaking any "click within N px
        of the tab's right edge" hit-test a visible per-tab (x) button
        would need via the normal API. identify()/index() at a
        coordinate DO work correctly, so the close action is anchored
        to those instead. See _on_tab_strip_left_click for how the
        visible "x" glyph now gets a real left-click hit-test too,
        working around the same bbox() gap a different way."""
        try:
            index = self.tab_strip.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        self._close_tab_by_index(index)

    def _on_tab_strip_left_click(self, event):
        """Left-click ON THE VISIBLE "x" glyph closes its tab (Devin,
        2026-07-26: "'x' on last document tab doesn't close it and go
        to home"). Real root cause: the "x" glyph was a visual hint
        only -- plain left-click has no built-in close behavior at
        all (only middle-click did, see _on_tab_strip_click), so
        clicking the thing that LOOKS clickable just reselected the
        tab (a no-op if it was already the active/only tab), which
        reads exactly as "doesn't close."

        Can't fix this with a pixel-offset hit-test the obvious way --
        ttk.Notebook.bbox() is confirmed broken (see
        _on_tab_strip_click's docstring) on both this dev box and a
        real Windows Tk build, so there's no reliable "this tab starts
        at x=N" to measure a close-zone against. Real workaround,
        empirically verified live (a hidden Tk probe, 2026-07-26):
        tab_strip.index(f"@{x},{y}") DOES resolve correctly at any
        coordinate even though bbox() lies -- scanning it forward one
        pixel at a time from the click point finds the real edge of
        the clicked tab, either where the index changes to the NEXT
        tab, or (critically, for the LAST tab -- the exact case in
        Devin's report) where querying past the last tab's real
        content raises a clean TclError instead of silently returning
        a wrong answer. Treats hitting the strip's own right edge
        (winfo_width()) as also in-bounds, matching a genuinely
        borderless case (a tab's real content can end exactly at the
        widget's edge with no further probing possible)."""
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
        # Slice 2 (Fable design review, 2026-07-25): genuinely branch
        # rather than thread view_mode ifs through one render path --
        # search-highlight/selection overlays both need "+ page offset"
        # in continuous mode, so unifying the two paths would mean
        # offset-plumbing every call site anyway. Two smaller, readable
        # functions instead.
        self._suppress_scroll_sync = True
        try:
            if self.continuous_scroll:
                self._render_continuous()
            else:
                self._render_static_row()
        finally:
            self._suppress_scroll_sync = False
        pending_here = sum(1 for p, _ in self._pending_redactions if p == self.viewer.page_num)
        # Page number moved to the centered Foxit-style box (Devin,
        # 2026-07-25) -- status now carries only zoom/pending-redaction.
        self.status.config(
            text=f"zoom {self.viewer.zoom:.2f}x"
            + (f"  ({pending_here} pending redaction)" if pending_here else "")
        )
        self.page_entry_var.set(str(self.viewer.page_num + 1))
        self.page_total_label.config(text=f"of {self.viewer.page_count}")

    def _colorize_for_theme(self, img):
        # Real gap Devin caught live: a raw invert (the first attempt)
        # only reads right for the plain built-in "dark" theme --  it
        # leaves every LIGHT-toned named theme's page pure white, not
        # tinted to that theme's own paper color, so the reading
        # surface doesn't match the chrome at all ("want document to
        # match" a themed page, "same as text editors when using
        # themes"). ImageOps.colorize maps the page's own light->dark
        # tones onto the theme's canvas_bg->fg pair instead of a flat
        # invert -- one mechanism for every theme, light or dark alike
        # (for the plain "light" theme this is a near no-op, black->
        # black and white->near-white). Photos/images on the page
        # recolor too, same accepted simple tradeoff as Sumatra's own
        # basic color-inversion feature, just via a nicer mapping.
        #
        # Opt-out, then flipped to opt-IN (both same day, 2026-07-26):
        # that tradeoff actively destroys content where color IS the
        # payload -- first caught live on a categorical-color-coded
        # diagram whose legend went meaningless once flattened to one
        # tint; recurred the same day on a real blue/orange bake-off
        # comparison diagram, which is what prompted flipping the
        # DEFAULT to off rather than leaving it an opt-out most people
        # would never find. self.colorize_pages now defaults False --
        # checking "Colorize pages to theme" in the View menu is how a
        # prose-only reader opts back into the old tinted-to-theme look.
        if not self.colorize_pages:
            return img
        colors = theme.get_palette(self.theme_name.get())
        return ImageOps.colorize(img.convert("L"), black=colors["fg"], white=colors["canvas_bg"])

    def _render_static_row(self):
        """The "not scrolling" axis (Slice 4, Fable design review,
        2026-07-25) -- side-by-side is an independent checkbox, not a
        third radio option, so this replaces the old single-page-only
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
        cols = 2 if self.side_by_side else 1
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
        screenful of slack (Fable design review, 2026-07-25, Slice 3
        perf consult) -- self-adjusts to zoom/viewport size, no tuned
        page-count constant.

        Trusts canvas.yview() -- only valid once the scrollregion
        reflects the CURRENT layout. Real bug caught live building
        this: calling this before a render pass updates the
        scrollregion reads a STALE fraction (from whatever the
        previous, differently-sized mode/layout had) against the NEW
        total_h, producing a nonsensical window that could span nearly
        the whole document. _render_continuous's first-ever build for
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
        """Real perf fix (Fable design review, 2026-07-25), after Devin
        hit a live lockup on PageUp/PageDown: the original eager-
        render-every-page-on-every-render()-call approach re-rasterized
        the WHOLE document on every navigation/zoom/theme change.
        Windowed instead -- only pages near the viewport (± one
        screenful of slack) get a real PhotoImage; everything else is a
        cheap colored placeholder rect, lazily upgraded as the window
        moves (see _shift_window, the pure-scroll incremental path that
        avoids even this full rebuild for ordinary scrolling)."""
        cols = 2 if self.side_by_side else 1
        zoom = self.viewer.zoom
        # Centering (Devin, 2026-07-29 -- "current default alignment isn't
        # centered"): continuous mode deliberately does NOT resize the
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
            # Devin, 2026-07-25, live screenshot review: a page that
            # ends with a lot of its own trailing whitespace (baked
            # into that page's real content, not something Slate can
            # crop without risking real content) reads as an
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
                # Starts at center_offset_x, not 0 -- with centering active
                # (Devin, 2026-07-29), x=0 is empty left margin, not the
                # real page edge; the line would otherwise bleed through
                # that dead space instead of tracking the actual content.
                self.canvas.create_line(
                    self._layout.center_offset_x, line_y, row_w, line_y,
                    fill=colors["muted_fg"], width=1,
                )
        total_w, total_h = self._layout.total_size
        # Deliberately NOT canvas.config(width=, height=) here (unlike
        # _render_single, where the canvas SHOULD size to exactly one
        # page) -- real bug caught live after defaulting view_mode to
        # "continuous": sizing the canvas WIDGET itself to the full
        # stacked document height meant that, on a fresh window with no
        # prior smaller render to anchor a sane size, Tk let the
        # TOPLEVEL grow to fit that huge request outright (nothing
        # existed yet to clip it against), so canvas.yview() reported
        # "everything fits" even for a document far taller than any
        # real screen. scrollregion alone is correct here -- the
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
        mode, so this is byte-identical to the pre-Slice-2 math there."""
        if not self.search_state.matches:
            return
        z = self.viewer.zoom
        current = self.search_state.current()
        for rect in self.search_state.matches_on_page(page_num):
            is_current = current is not None and current[0] == page_num and current[1] == rect
            outline = "red" if is_current else "yellow"
            width = 3 if is_current else 2
            self.canvas.create_rectangle(
                ox + rect.x0 * z, oy + rect.y0 * z, ox + rect.x1 * z, oy + rect.y1 * z,
                outline=outline, width=width,
            )

    def _draw_text_selection_for_page(self, page_num, ox, oy):
        """Canvas-only overlay, same convention as
        _draw_search_highlights_for_page -- cleared and redrawn every
        render() alongside the page image, never a real annotation.
        Uses the active theme's highlight_bg (was a hardcoded blue
        "#3a5a7a" regardless of theme) -- for inkbone this is the one
        place green survives as a real, minimal, pure accent (Devin,
        2026-07-25), not select_bg (tabs, now monochrome). A selection
        holds (page_num, word) pairs now (Devin, 2026-07-26: cross-page
        selection) -- each page draws only its own words, filtered out
        of the whole selection here, so a selection spanning several
        pages still renders correctly, once per resident page.

        Devin, 2026-07-25: "make it a true highlighter" -- this used to
        draw one stippled rectangle PER SELECTED WORD, which read as a
        scattered multicursor-style pattern (gaps between words, a
        dithered fill) instead of one smooth highlighter bar. Same two
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

        Real bug caught live 2026-07-26 ("TTS highlight works, drag
        selection doesn't"): this function runs once per VISIBLE page
        (_draw_real_page is called for every resident page in the
        window, and continuous mode routinely has 2+ pages resident).
        The old version reset self._selection_highlight_photos = []
        on EVERY non-matching page's early return -- so the correct
        page's images got created and drawn, then wiped by the very
        next page processed in the SAME render pass (whichever page
        that was, matching or not), going blank before the frame was
        even fully drawn. Fix: this function only ever APPENDS its own
        page's images to the list (via the caller having already reset
        it once for the whole pass); a non-matching page does a bare
        return, touching nothing."""
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
        overlay, reused here (Devin, 2026-07-26: "a good right-click
        menu... include things users would expect") so "Highlight
        Selection"/"Redact Selection" mark exactly what the on-screen
        highlight visually shows, page by page across a cross-page
        selection."""
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
        for page_num, rect in self._selection_line_rects():
            annotate.add_highlight(self.doc[page_num], rect)
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
        surprising, not helpful). Devin, 2026-07-26: "a good right-click
        menu... include things that should be there and users would
        expect to see" -- the standard PDF-reader set this app can
        actually back with a real feature: Copy/Highlight/Redact
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
        step = 2 if self.side_by_side else 1
        self._go_to_page(min(self.viewer.page_num + step, self.viewer.page_count - 1))

    def prev(self):
        """See next()'s docstring."""
        if self.viewer is None:
            return
        if self.viewer.page_num <= 0:
            return
        step = 2 if self.side_by_side else 1
        self._go_to_page(max(self.viewer.page_num - step, 0))

    def _prev_page_landing_at_bottom(self):
        """Same as prev(), except a wheel-driven page-turn arrives from
        BELOW (scrolling up past the top edge) and should land at the
        new page's bottom, not its top -- asymmetric from every other
        prev-page trigger (keyboard/j/PageUp/TOC-select all keep
        landing top-left via prev()+_reset_scroll(), unchanged, per
        Fable's design review 2026-07-25: don't touch those paths)."""
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
        """Rubber-band wheel (Fable design review, 2026-07-25): page-
        turn only when the page already fits the viewport OR the view
        is scrolled to the very top edge; otherwise real scroll.
        Direction-only -- X11 Button-4 and Windows/Mac MouseWheel(up)
        both call this, neither needs delta magnitude for this logic
        (a real gap Fable flagged: those two platforms went through
        DIFFERENT code paths before this fix, which happened to agree
        only because both did the same unconditional thing).

        Continuous mode (Slice 2, Fable design review): page
        boundaries are a soft concept once every page is stacked in
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
                # reliable trigger in every environment (confirmed live:
                # plain yview_moveto()/scrollbar-drag didn't fire it
                # under this dev box's headless Xvfb, even after
                # root.update()) -- called explicitly so the page-number
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
        """Ctrl+scroll = zoom (Devin, 2026-07-25), same signed-delta
        convention as _on_mouse_wheel above."""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _on_shift_mouse_wheel(self, event):
        """Shift+scroll = horizontal scroll (Devin, 2026-07-26). Windows/Mac
        deliver a signed event.delta same as plain wheel; X11 has no
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
        # Manual command, not an auto-apply-on-open default (Devin,
        # 2026-07-26): a genuinely oversized page (a landscape diagram
        # PDF) opening at literal 1:1-ish DEFAULT_ZOOM and running
        # off-screen is a real bug, but auto-fitting on every open was
        # tried first and reverted -- it broke 131 existing tests that
        # hardcode DEFAULT_ZOOM as document-open's fixed, predictable
        # starting point (zoom_in/out deltas, cache-invalidation checks,
        # wheel-scroll page-fit math). Same update_idletasks() timing
        # fix still applies here (Tk's next idle-loop pass otherwise
        # reports a stale canvas width).
        self.canvas.update_idletasks()
        viewport_w = self.canvas.winfo_width()
        if viewport_w > 1:
            self.viewer.fit_width(viewport_w)
            self.render()
            settings.save({"zoom": self.viewer.zoom})

    # ------------------------------------------------------------------
    # canvas interaction (redact / annotate / forms all live here)
    # ------------------------------------------------------------------
    def _page_offset(self, page_num):
        """(x0, y0) canvas-space origin of this page, exactly matching
        wherever it was actually drawn. Generalizes to "does
        self._layout exist" (Fable design review, Slice 4) rather than
        a mode check -- self._layout exists in all four continuous_
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
        test (Devin, 2026-07-26)."""
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
        now. Adding real scrollbars (Devin, 2026-07-25: "and a h/v
        scrollbar") means every click/drag handler needs this
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
        # Anchor point for a real text-flow selection (Devin, 2026-07-26:
        # "mouse down should be point of highlight start... continuous
        # highlight like you'd expect a highlight tool to do") -- fixed
        # for the whole gesture, in PDF space so it survives scrolling.
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
            # Real text-FLOW selection (Devin, 2026-07-26: "mouse down
            # should be point of highlight start, dragging direction
            # determines which direction and how long highlight goes...
            # continuous highlight like you'd expect a highlight tool
            # to do") -- not a geometric rectangle-intersection test.
            #
            # History of two wrong approaches this replaces, both real
            # bugs caught live the same day: (1) plain rect-intersection
            # against every word on the page selected every line the
            # drag's bounding box happened to cross, even lines/
            # paragraphs only partly overlapped -- looked like several
            # disconnected lines highlighting at once. (2) restricting
            # to whichever single line sits nearest the CURRENT cursor
            # position fixed that, but made the highlight jump from
            # line to line as the mouse moved instead of accumulating
            # a continuous run -- not how a real highlighter/text
            # selection works.
            #
            # Real fix: PyMuPDF's get_text("words") is already in
            # natural reading order (top-to-bottom, left-to-right) --
            # find the word index nearest the drag's ANCHOR (mouse-down
            # point, pinned in self._drag_anchor_pdf) and the word index
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
            # on. Real bug caught live 2026-07-26 ("highlighter doesn't do
            # anything"), not a rendering/compositing problem.
            # Cross-page extension (Devin, 2026-07-26: "i want the
            # highlight feature to not be restricted to a single page")
            # -- self._selected_words now holds (page_num, word) pairs
            # instead of bare words, so a selection can span every page
            # it visually crosses in continuous scroll, not just the one
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
            # multi-region redaction pass (and made this exact code path
            # fragile to test/automate -- a real hang was hit live during
            # development from a dialog nothing was there to dismiss).
            # render()'s own status bar already shows the pending count
            # for the current page; that's the real, non-blocking feedback.
            # self.page.number (not self.viewer.page_num): a latent bug
            # Fable flagged in design review -- invisible in single-page
            # mode where they're always equal, real the moment a drag
            # can land on any visible page (continuous mode).
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
            # Real, serious bug caught live 2026-07-25 wiring the
            # HTML/image-open feature: self.path is the ORIGINAL path
            # (tab convention) even when the actual open document is a
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
        # Real bug caught live: Tkinter is not thread-safe -- calling
        # self.root.after(...) FROM the worker thread (as the progress
        # callback originally did) raised "main thread is not in main
        # loop". The worker now only ever writes to this plain dict
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
        """Devin, 2026-07-25: "TTS: read entire document, not just
        current page." Reads from the current page onward, auto-
        advancing (page nav + the reading-position highlight both
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
        synchronously on the main thread, as this originally did,
        froze the whole UI for the duration -- likely the real source
        of Devin's 'kinda choppy sometimes' report. Synthesis now runs
        on a background thread; poll() (scheduled via self.root.after(),
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
        """Right-click a word in view mode -> "Read from here" (Devin,
        2026-07-26: "a way to tell TTS where to start reading"), same
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
        progress against the SAME words that were actually synthesized
        -- real bug fixed here (Devin, 2026-07-26: "'read from here'
        starts at the top of the page, not the point of my mouse"): the
        highlight used to always re-derive the FULL page's words from
        scratch, oblivious to a "read from here" click trimming the
        start, so its progress estimate raced through words that were
        never even sent to the synthesizer."""
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
        # Devin, 2026-07-25, "make the default... voice slower, more
        # natural pace... base other speeds around that" -- "1.0x" is
        # now a calibrated natural default, not Piper's raw native rate.
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

        # Real crash caught live building Slice 3 (after defaulting
        # view_mode to "continuous" made every test do more Tk work
        # sooner after doc-open, widening a pre-existing race window):
        # tests only polled the _tts_synthesizing FLAG, not this actual
        # thread object -- there's a razor-thin gap between the flag
        # flipping False (inside worker(), just before it returns) and
        # the OS thread genuinely finishing. A test that only trusts
        # the flag can proceed (and tear down, letting the NEXT test's
        # main-thread Tk calls run) while this thread is still mid-
        # teardown after its first-ever `import piper` -- a real
        # cross-test race that segfaulted. self._tts_thread is kept so
        # tests can .join() it for a real guarantee, not just the flag.
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
        """Toolbar quick-access button (Devin, 2026-07-25: "easier
        audio readback controls, preferably also available on the
        main toolbar") -- one button that does whichever action makes
        sense right now instead of making the user pick the right menu
        command: starts reading the current page if nothing's loaded
        yet, otherwise toggles pause/resume of what's already loaded."""
        if self.tts_player.has_audio():
            self.do_tts_pause_resume()
        else:
            self.do_read_page()

    def _on_tts_voice_changed(self):
        """Real bug report (Devin, 2026-07-25): "changing voices
        mid-read is not working." Root cause: the Voice menu's
        radiobuttons had no command callback at all -- selecting a
        different voice only updated the tts_voice StringVar, with
        nothing to actually apply it. Whatever was already loaded (or
        mid-synthesis) just kept playing in the OLD voice with no way
        to hear the new selection short of manually stopping and
        clicking "Read this page" again. Real fix: if something is
        already loaded, selecting a voice restarts the CURRENT page
        fresh in the new one -- do_read_page() already stops old
        playback itself (Player.load()'s own stop() call). Mid-
        synthesis (audio not loaded yet) is a real, accepted gap left
        for later: do_read_page()'s own _tts_synthesizing guard would
        block a same-instant re-trigger, and synthesis is fast enough
        (~1s) that this is a narrow window, not the reported bug."""
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
        """Devin, 2026-07-25: "is there a way to tell what is the
        current voice/speed is on readback? that might be a good
        application for our green accent." Real, minimal answer:
        voice name + speed multiplier, shown only while something is
        actually loaded (empty otherwise, so it doesn't clutter the
        toolbar the rest of the time)."""
        if not self.tts_player.has_audio():
            return ""
        voice_label = tts.VOICES.get(self.tts_voice.get(), {}).get("label", self.tts_voice.get())
        return f"\U0001F50A {voice_label} · {self.tts_speed.get():g}x"

    def _update_tts_highlight(self):
        """Devin, 2026-07-25, same message as the status text ask: a
        real "follow along" highlight for what's currently being read,
        using the house green accent (the one other place, besides
        text selection, green is allowed to appear per the manga-
        essence minimal-accent rule).

        Honest limitation, not hidden: Piper's simple synthesize() API
        (tts.py) returns raw audio only, no per-word timing/alignment
        data -- there's no real way to know exactly which word is
        playing at any instant. Estimated as a fraction of the page's
        text proportional to Player.progress (0.0-1.0 through the
        audio), weighted by CHARACTER count rather than plain word
        count (Devin, 2026-07-25, real feedback: "the indicator is
        off") -- a 12-letter word takes noticeably longer to speak
        than "a", so a per-word index alone drifted visibly out of
        sync over a page; a character-weighted cumulative position is
        still an estimate (no true audio alignment exists to check
        against) but tracks materially better.

        Drawn as ONE merged rectangle over words sharing the current
        line (Devin, same message: "it also looks weird...
        rasterized... not a natural highlight") -- the earlier version
        drew 2-3 SEPARATE small stippled boxes, which visibly
        fragmented (and could jump to the start of the NEXT line
        mid-window, drawing two disconnected boxes) instead of reading
        as one smooth highlight. Constraining the window to one line
        (PyMuPDF's own line_no field) and merging into a single
        rectangle fixes the fragmentation.

        STILL rasterized after that fix (Devin, 2026-07-26, same
        complaint recurring: "coloring in between letters instead of
        true highlight") -- root cause was `stipple`, not the box
        count. Tk canvas fill colors have no alpha channel; `stipple`
        is Tk's only built-in fake-transparency trick, and it works by
        literally not painting ~75% of the pixels in a fixed dot
        pattern, which reads exactly as "rasterized" because it is.
        Real fix: build a genuinely translucent RGBA PhotoImage (Tk
        8.6+ canvas images DO alpha-composite for real against
        whatever's already drawn underneath) and draw that instead of
        a stippled rectangle -- a true semi-transparent highlighter
        color over the text, not a dither pattern.

        Cleared (canvas.delete by tag) whenever nothing's loaded, or
        when the page being read isn't part of what's currently drawn
        (scrolled/navigated away -- nothing to overlay onto)."""
        self.canvas.delete("tts_highlight")
        page_num = self._tts_reading_page_num
        if page_num is None or not self.tts_player.has_audio() or self._tts_reading_page is None:
            return
        if self._layout is not None and page_num not in self._last_window:
            return  # not currently drawn -- nothing to overlay onto
        # self._tts_reading_words (Devin, 2026-07-26 fix), NOT a fresh
        # self._tts_reading_page.get_text("words") -- that used to
        # silently ignore a "read from here" start offset, estimating
        # progress against every word on the page instead of only the
        # ones actually sent to the synthesizer.
        words = self._tts_reading_words
        if not words:
            return
        # Real mechanism behind "TTS indicator is too fast" (Devin,
        # 2026-07-26). Piper inserts a genuine pause at sentence ends
        # and a much smaller one at clause breaks -- real elapsed audio
        # time producing zero new characters of speech; a flat +1-per-
        # word model charges punctuation the same time-cost as any
        # letter, implicitly assuming pauses take no time. Weights below
        # are MEASURED, not guessed: headless A/B synthesis via this
        # exact voice/length_scale (northern_english_male, 1.0x),
        # holding word content fixed and comparing a sentence-final
        # period against a mid-sentence comma at the identical
        # position, then solving for the extra pause time in character-
        # equivalents. Real result: a period costs ~9.3 char-equivalents
        # of pause; a comma costs only ~0.7 (my first guess of +8/+3 had
        # the comma 4x too high -- wrong direction for "too fast," and
        # negligible either way).
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

        # Per-SENTENCE calibration (Devin, 2026-07-26: "build the real
        # alignment version"). True per-phoneme alignment was
        # investigated and ruled out: confirmed live that these voice
        # models' ONNX sessions return only one output tensor (audio),
        # so `include_alignments=True` yields nothing to use --
        # tts.synthesize() was never built with the duration-output
        # branch this needs. What IS real and available: Piper still
        # synthesizes one audio chunk per SENTENCE, and
        # tts.synthesize() now returns each chunk's real sample count
        # (self._tts_chunk_sample_counts, set in _read_current_page).
        # Grouping `words` into sentences (splitting after any word
        # ending in .!?) and pairing each group 1:1 with a real chunk
        # duration turns "one uniform character-rate guess across the
        # WHOLE PAGE" into "one uniform rate per SENTENCE, with real
        # measured pauses between them" -- a much smaller, more honest
        # approximation window, without needing model-level alignment
        # support that doesn't exist here.
        #
        # Real risk, handled rather than ignored: my sentence split is
        # a simple heuristic and won't always match Piper/espeak's own
        # internal sentence boundaries -- an abbreviation like "vv." or
        # "Jer." (both real strings in Devin's own sermon-note PDFs)
        # can fool it into splitting where espeak didn't. Rather than
        # silently mismatching chunk N to the wrong sentence, the
        # sentence COUNT is checked against the real chunk count first;
        # any mismatch falls back to the same whole-page weighted
        # estimate this function already used (still real, still
        # correctly calibrated punctuation weights -- just without
        # per-sentence pause precision), never a guess dressed as a
        # confident per-sentence position.
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
        # the PREVIOUS line. Real bug caught live 2026-07-26 ("TTS
        # indicator is too fast"): this used to take words[idx:idx+6],
        # i.e. the current word PLUS the next 5 -- so the highlight's
        # leading edge always showed 5 words not yet spoken, which
        # reads exactly as "racing ahead of the audio." A trailing
        # window (already-spoken words ending at the current estimate)
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
        of polling forever -- except mid "read entire document"
        (Devin, 2026-07-25), where reaching a real natural end (was
        playing, now isn't, and NOT because of an explicit pause --
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
    entry. Devin, 2026-07-25: "make the icon(s) official in the
    taskbar/titlebar" -- iconbitmap() alone (_set_window_icon) doesn't
    fix the grouping half of that ask, only the icon-image half.
    Best-effort, same fail-soft pattern as _apply_native_titlebar_theme.
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

    # Single-instance (Devin, 2026-07-25): if a Slate window is already
    # running, hand this path to it as a new tab instead of opening a
    # second window. Only meaningful when a path was actually given --
    # a bare `slate.py` with nothing to open has nothing to hand off.
    if path and singleinstance.try_send_to_running_instance(path):
        return

    root = tk.Tk()
    app = SlateApp(root, path)

    # Restore window size+position (Devin, 2026-07-26: "remember window
    # size, location, etc"). A saved geometry wins outright -- it
    # already encodes both size and position together, nothing left for
    # the centering logic below to add. Only a genuine first-ever launch
    # (or a corrupt/missing settings file, load()'s own fallback) has no
    # saved value, in which case centering (Devin, 2026-07-25: "Slate is
    # still opening in top left of screen, can you make that center load
    # plz?") is still the right first-run default. update_idletasks()
    # first either way -- real geometry only exists once the home
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
        # Final position checkpoint (Devin, 2026-07-26) -- _go_to_page's
        # own checkpoints cover explicit navigation, but plain scrolling
        # in continuous mode isn't saved on every tick (real I/O cost);
        # this catches wherever that actually left things before the
        # window really closes.
        app._save_open_tabs()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

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
