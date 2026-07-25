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
from PIL import ImageOps, ImageTk

import annotate
import convert
import epubfix
import forms
import gate
import io_pdf
import merge_split
import recent
import redact
import scan
import search
import security
import sign
import singleinstance
import tab as tabmodule
import textedit
import theme
import tts
import updatecheck
import version
from viewer import Viewer
from playback import Player as TTSPlayer

_TAB_CLOSE_GLYPH = "×"  # visual hint only -- middle-click actually closes, see _on_tab_strip_click

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
        self.path = None
        self.doc = None
        self.viewer = None
        self.page = None
        self._tk_img = None  # keep a reference or Tkinter garbage-collects it
        self.mode = "view"  # view | redact | annotate:<kind> | forms | textedit
        self._drag_start = None
        self._drag_rect_id = None
        self._pending_redactions = []  # [(page_num, fitz.Rect), ...]
        # Text selection (view mode default -- Devin's ask, 2026-07-25:
        # "default to arrow/select text over rectangle select"). Each
        # entry is a fitz word tuple (x0, y0, x1, y1, word, block_no,
        # line_no, word_no) -- page.get_text("words") already returns
        # words in natural reading order, so the selected subset stays
        # correctly ordered without re-sorting by geometry.
        self._selected_words = []
        self._doc_view_built = False
        self.home_frame = None
        # Devin, 2026-07-25: "default TOC view = true."
        self.toc_visible = tk.BooleanVar(value=True)
        self.theme_name = tk.StringVar(value=theme.load_preference())
        # Read Aloud (TTS): app-wide, not per-tab -- reading one document
        # while switching tabs isn't a supported combination in v1.
        self.tts_voice = tk.StringVar(value="northern_english_male")
        self.tts_speed = tk.DoubleVar(value=1.0)  # user-facing multiplier, not Piper's length_scale directly
        self.tts_player = TTSPlayer()
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
            self._open_document(path)
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
            self.render()  # re-invert the currently-visible page immediately, not on next nav

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
        # i cannot see the menu checkboxes" -- Tk's radiobutton/
        # checkbutton indicator (selectcolor) defaults to a mid-gray
        # that can vanish against a dark native menu background.
        # Fixed value, not re-themed live on theme switch (the native
        # Win32 menu popup itself is already a documented can't-fully-
        # control surface, see theme.py's own docstring) -- bright
        # green reads against light OR dark menu backgrounds, so a
        # static pick here is more robust than trying to track/re-
        # theme every radiobutton entry through every theme switch.
        radio_select_color = "#4a9e3a"
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
        viewm.add_separator()
        thememenu = tk.Menu(viewm, tearoff=0)
        for label, name in theme.THEME_LABELS.items():
            thememenu.add_radiobutton(
                label=label, variable=self.theme_name, value=name,
                command=self._on_theme_changed, selectcolor=radio_select_color,
            )
        viewm.add_cascade(label="Theme", menu=thememenu)
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
                selectcolor=radio_select_color,
            )
        readm.add_cascade(label="Voice", menu=voicem)
        speedm = tk.Menu(readm, tearoff=0)
        for speed in (0.75, 1.0, 1.25, 1.5, 2.0):
            speedm.add_radiobutton(
                label=f"{speed}x", variable=self.tts_speed, value=speed,
                selectcolor=radio_select_color,
            )
        readm.add_cascade(label="Speed", menu=speedm)
        readm.add_separator()
        readm.add_command(label="Read this page", command=self.do_read_page)
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

    def _set_mode(self, mode):
        self.mode = mode
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
        px, py = cx / z, cy / z
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
        self.canvas = tk.Canvas(canvas_frame, bg="gray80")
        self._vscroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self._hscroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self._vscroll.set, xscrollcommand=self._hscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")
        self._hscroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        self._canvas_frame = canvas_frame  # _toggle_toc_panel needs the PANE widget, not the bare canvas
        content.add(canvas_frame, stretch="always")
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

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
        # Mouse wheel: Windows/Mac deliver <MouseWheel> with a signed
        # event.delta; X11/Linux (this dev environment) instead sends
        # discrete Button-4 (up) / Button-5 (down) click events with no
        # delta at all -- both bound so this is actually testable here,
        # not just assumed to work on the real deployment target.
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", self._kb_prev_page)
        self.canvas.bind("<Button-5>", self._kb_next_page)
        # Ctrl+scroll = zoom (Devin, 2026-07-25), same platform split as
        # plain wheel above -- Tk's compound event names route the
        # Control-modified wheel to a separate binding automatically,
        # no manual event.state check needed.
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mouse_wheel)
        self.canvas.bind("<Control-Button-4>", lambda e: self.zoom_in())
        self.canvas.bind("<Control-Button-5>", lambda e: self.zoom_out())

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

        # CUA keybinds (Devin, 2026-07-25: "ctrl+w close tab (and other
        # CUA keybinds)") -- the standard Windows/Mac shortcut set,
        # matching menu accelerators added alongside these.
        self.root.bind("<F2>", self._show_command_palette)
        self.root.bind("<Control-w>", lambda e: self.do_close())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.bind("<Control-S>", lambda e: self.save_as())  # Ctrl+Shift+S
        self.root.bind("<Control-f>", self._kb_open_find)  # alongside "/", not a replacement
        self.root.bind("<Control-q>", lambda e: self.root.quit())
        self.root.bind("<Control-plus>", lambda e: self.zoom_in())
        self.root.bind("<Control-equal>", lambda e: self.zoom_in())  # Ctrl+= (no-Shift + key, most keyboards)
        self.root.bind("<Control-minus>", lambda e: self.zoom_out())
        self.root.bind("<Control-Tab>", self._kb_next_tab)
        self.root.bind("<Control-Shift-Tab>", self._kb_prev_tab)
        self.root.bind("<Control-Next>", self._kb_next_tab)  # Ctrl+PageDown, browser-tab convention
        self.root.bind("<Control-Prior>", self._kb_prev_tab)  # Ctrl+PageUp

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
        self.viewer.goto(n - 1)
        self._selected_words = []
        self.render()
        self._reset_scroll()

    def _kb_first_page(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self.viewer.goto(0)
        self._selected_words = []
        self.render()
        self._reset_scroll()

    def _kb_last_page(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self.viewer.goto(self.viewer.page_count - 1)
        self._selected_words = []
        self.render()
        self._reset_scroll()

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
            self.viewer.goto(page_num)
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
        self.viewer.goto(int(values[0]))
        self._selected_words = []
        self.render()
        self._reset_scroll()

    # ------------------------------------------------------------------
    # opening / closing documents
    # ------------------------------------------------------------------
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
        # Tab keeps the ORIGINAL path (tab label/title/recent-files all
        # show the real filename) even when doc was actually opened
        # from a corrected temp copy.
        new_tab = tabmodule.Tab(path, doc, Viewer(doc))
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
        (0,0,0,0) for every tab in this dev environment (confirmed
        across both the 'default' and 'clam' themes) despite the
        widget being mapped with real, non-zero dimensions -- breaking
        any "click within N px of the tab's right edge" hit-test a
        visible per-tab (x) button would need. identify()/index() at a
        coordinate DO work correctly here, so the close action is
        anchored to those instead of to unreliable per-tab pixel
        bounds. The trailing close glyph in each tab's label is a
        visual hint only, not an actual separate click target."""
        try:
            index = self.tab_strip.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        self._close_tab_by_index(index)

    def _close_tab_by_index(self, index):
        closing_tab = self._tabs.pop(index)
        closing_frame = self._tab_frames.pop(index)
        was_active = closing_tab is self._active_tab
        closing_tab.doc.close()
        self.tab_strip.forget(closing_frame)
        closing_frame.destroy()

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
        img = self.viewer.render_page()
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
        colors = theme.get_palette(self.theme_name.get())
        img = ImageOps.colorize(img.convert("L"), black=colors["fg"], white=colors["canvas_bg"])
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.config(width=img.width, height=img.height)
        self.canvas.config(scrollregion=(0, 0, img.width, img.height))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)
        self._draw_search_highlights()
        self._draw_text_selection()
        pending_here = sum(1 for p, _ in self._pending_redactions if p == self.viewer.page_num)
        # Page number moved to the centered Foxit-style box (Devin,
        # 2026-07-25) -- status now carries only zoom/pending-redaction.
        self.status.config(
            text=f"zoom {self.viewer.zoom:.2f}x"
            + (f"  ({pending_here} pending redaction)" if pending_here else "")
        )
        self.page_entry_var.set(str(self.viewer.page_num + 1))
        self.page_total_label.config(text=f"of {self.viewer.page_count}")

    def _draw_search_highlights(self):
        """Canvas-only overlay, not real annotations -- cleared and
        redrawn every render() same as the page image itself."""
        if not self.search_state.matches:
            return
        z = self.viewer.zoom
        current = self.search_state.current()
        for rect in self.search_state.matches_on_page(self.viewer.page_num):
            is_current = current is not None and current[0] == self.viewer.page_num and current[1] == rect
            outline = "red" if is_current else "yellow"
            width = 3 if is_current else 2
            self.canvas.create_rectangle(
                rect.x0 * z, rect.y0 * z, rect.x1 * z, rect.y1 * z,
                outline=outline, width=width,
            )

    def _draw_text_selection(self):
        """Canvas-only overlay, same convention as
        _draw_search_highlights -- cleared and redrawn every render()
        alongside the page image, never a real annotation. Uses the
        active theme's highlight_bg (was a hardcoded blue "#3a5a7a"
        regardless of theme) -- for inkbone this is the one place
        green survives as a real, minimal, pure accent (Devin,
        2026-07-25), not select_bg (tabs, now monochrome)."""
        if not self._selected_words:
            return
        colors = theme.get_palette(self.theme_name.get())
        z = self.viewer.zoom
        for w in self._selected_words:
            x0, y0, x1, y1 = w[:4]
            self.canvas.create_rectangle(
                x0 * z, y0 * z, x1 * z, y1 * z,
                fill=colors["highlight_bg"], outline="", stipple="gray50",
            )

    def _selected_text(self) -> str:
        return " ".join(w[4] for w in self._selected_words)

    def _copy_selection(self, event=None):
        text = self._selected_text()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def next(self):
        if self.viewer is None:
            return
        self.viewer.next_page()
        self._selected_words = []  # a selection's word rects belong to the OLD page
        self.render()
        self._reset_scroll()

    def prev(self):
        if self.viewer is None:
            return
        self.viewer.prev_page()
        self._selected_words = []
        self.render()
        self._reset_scroll()

    def _on_mouse_wheel(self, event):
        """Windows/Mac only -- delivers a signed event.delta (Windows:
        +/-120 per notch); X11 has no <MouseWheel> event at all, wheel
        arrives as Button-4/Button-5 clicks instead (bound separately)."""
        if event.delta > 0:
            self._kb_prev_page()
        else:
            self._kb_next_page()

    def _on_ctrl_mouse_wheel(self, event):
        """Ctrl+scroll = zoom (Devin, 2026-07-25), same signed-delta
        convention as _on_mouse_wheel above."""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def zoom_in(self):
        self.viewer.zoom_in()
        self.render()

    def zoom_out(self):
        self.viewer.zoom_out()
        self.render()

    # ------------------------------------------------------------------
    # canvas interaction (redact / annotate / forms all live here)
    # ------------------------------------------------------------------
    def _canvas_to_pdf_rect(self, x0, y0, x1, y1) -> fitz.Rect:
        z = self.viewer.zoom
        return fitz.Rect(
            min(x0, x1) / z, min(y0, y1) / z, max(x0, x1) / z, max(y0, y1) / z
        )

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
        cx, cy = self._event_canvas_xy(event)
        self._drag_start = (cx, cy)
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
            # Real text selection, not a rectangle mark -- default
            # interaction (Devin, 2026-07-25: "default to arrow/select
            # text over rectangle select"). Redact/annotate modes below
            # keep the original rectangle-drag behavior unchanged.
            rect = self._canvas_to_pdf_rect(x0, y0, cx, cy)
            words = self.page.get_text("words")
            self._selected_words = [w for w in words if fitz.Rect(w[:4]).intersects(rect)]
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
        rect = self._canvas_to_pdf_rect(x0, y0, cx, cy)
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
            self._pending_redactions.append((self.viewer.page_num, rect))
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
        px, py = cx / z, cy / z
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
        path = filedialog.askopenfilename(filetypes=[
            ("PDF, ebook, HTML and image files",
             "*.pdf *.epub *.mobi *.fb2 *.cbz *.txt *.md *.html *.htm *.png *.jpg *.jpeg *.gif *.bmp *.tiff"),
            ("PDF files", "*.pdf"),
            ("Ebook files", "*.epub *.mobi *.fb2 *.cbz *.txt *.md"),
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
        if getattr(self, "_tts_synthesizing", False):
            return  # a previous read is still being synthesized

        text = self.page.get_text().strip()
        if not text:
            messagebox.showinfo("Nothing to read", "This page has no extractable text.")
            return

        voice_id = self.tts_voice.get()
        if not self._ensure_voice_available(voice_id):
            return

        length_scale = 1.0 / self.tts_speed.get()
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
            audio, sample_rate, _width, channels = result["audio"]
            try:
                self.tts_player.load(audio, sample_rate, channels)
                self.tts_player.play()
            except Exception as e:
                messagebox.showinfo("Playback failed", str(e))

        threading.Thread(target=worker, daemon=True).start()
        poll()

    def do_tts_pause_resume(self):
        if self.tts_player.is_playing():
            self.tts_player.pause()
        else:
            try:
                self.tts_player.play()
            except Exception as e:
                messagebox.showinfo("Playback failed", str(e))

    def do_tts_stop(self):
        self.tts_player.stop()

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

    # Center on screen, not the top-left corner (Devin, 2026-07-25:
    # "Slate is still opening in top left of screen, can you make that
    # center load plz?") -- real geometry only exists once the home
    # screen/document widgets above are actually laid out, hence
    # update_idletasks() first, same pattern as _show_about's own
    # centering (which centers over the main window; this one has no
    # parent window to center over, so it centers on the screen itself).
    root.update_idletasks()
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    win_w, win_h = root.winfo_width(), root.winfo_height()
    root.geometry(f"+{(screen_w - win_w) // 2}+{(screen_h - win_h) // 2}")

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
