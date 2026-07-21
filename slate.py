#!/usr/bin/env python3
"""Slate — entry point and UI integration. Wires viewer, redact,
annotate, merge_split, forms, sign, security, scan, recent, io_pdf
together into one menu-driven app. Business logic lives in the
per-feature modules; this file is glue + Tkinter widgets only.
"""
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import fitz  # PyMuPDF
from PIL import ImageTk

import annotate
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
import textedit
import version
from viewer import Viewer

class SlateApp:
    def __init__(self, root, path=None):
        self.root = root
        self.path = None
        self.doc = None
        self.viewer = None
        self.page = None
        self._tk_img = None  # keep a reference or Tkinter garbage-collects it
        self.mode = "view"  # view | redact | annotate:<kind> | forms | textedit
        self._drag_start = None
        self._drag_rect_id = None
        self._pending_redactions = []  # [(page_num, fitz.Rect), ...]
        self._doc_view_built = False
        self.home_frame = None
        self.toc_visible = tk.BooleanVar(value=False)
        # Gated feature (DESIGN.md's "Text editing"): a local UX gate,
        # not real access control -- re-locks every restart on purpose.
        self._textedit_unlocked_this_session = False
        self.search_state = search.SearchState()

        root.title("Slate")
        self._build_menu()

        if path:
            self._open_document(path)
        else:
            self._show_home_screen()

    # ------------------------------------------------------------------
    # menu
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open...", command=self.open_file)
        self.recent_menu = tk.Menu(filem, tearoff=0, postcommand=self._refresh_recent_menu)
        filem.add_cascade(label="Recent", menu=self.recent_menu)
        filem.add_command(label="Close", command=self.do_close)
        filem.add_command(label="Save", command=self.save)
        filem.add_command(label="Save As...", command=self.save_as)
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
        filem.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=filem)

        editm = tk.Menu(menubar, tearoff=0)
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
        menubar.add_cascade(label="View", menu=viewm)

        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About Slate...", command=self._show_about)
        menubar.add_cascade(label="Help", menu=helpm)

        self.root.config(menu=menubar)

    def _show_about(self):
        top = tk.Toplevel(self.root)
        top.title("About Slate")
        top.resizable(False, False)
        tk.Label(
            top, text=f"Slate {version.VERSION}", font=("TkDefaultFont", 14, "bold")
        ).pack(padx=24, pady=(18, 6))
        tk.Label(
            top, text=version.SUMMARY, wraplength=360, justify="left"
        ).pack(padx=24, pady=(0, 18))
        tk.Button(top, text="Close", command=top.destroy).pack(pady=(0, 14))

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
        signed = " [SIGNED]" if sign.is_signed(self.path) else ""
        return f"Slate — {os.path.basename(self.path)}{signed}"

    def _set_mode(self, mode):
        self.mode = mode
        self.mode_label.config(text=f"mode: {mode}")

    def _require_doc(self) -> bool:
        if self.doc is None:
            messagebox.showinfo("No document", "Open a PDF first (File > Open).")
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

        tk.Label(self.home_frame, text="Slate", font=("TkDefaultFont", 20, "bold")).pack(
            anchor="w"
        )
        tk.Button(self.home_frame, text="Open PDF...", command=self.open_file).pack(
            anchor="w", pady=(10, 16)
        )

        tk.Label(self.home_frame, text="Recently viewed", font=("TkDefaultFont", 12, "bold")).pack(
            anchor="w"
        )
        entries = recent.get_recent()
        if not entries:
            tk.Label(self.home_frame, text="No recently viewed files", fg="gray40").pack(
                anchor="w", pady=6
            )
        else:
            listbox = tk.Listbox(self.home_frame, width=80, height=min(10, len(entries)))
            for e in entries:
                listbox.insert("end", e["path"])
            listbox.pack(fill=tk.BOTH, expand=True, pady=6)

            def open_selected(event=None):
                sel = listbox.curselection()
                if sel:
                    self._open_document(listbox.get(sel[0]))

            listbox.bind("<Double-Button-1>", open_selected)
            listbox.bind("<Return>", open_selected)

    # ------------------------------------------------------------------
    # document view (toolbar + canvas + toc panel) -- built once, reused
    # ------------------------------------------------------------------
    def _ensure_doc_view_widgets(self):
        if self._doc_view_built:
            return

        self.body_frame = tk.Frame(self.root)

        toolbar = tk.Frame(self.body_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(toolbar, text="< Prev", command=self.prev).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Next >", command=self.next).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Zoom -", command=self.zoom_out).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Zoom +", command=self.zoom_in).pack(side=tk.LEFT)
        self.mode_label = tk.Label(toolbar, text="mode: view", fg="blue")
        self.mode_label.pack(side=tk.LEFT, padx=12)
        self.status = tk.Label(toolbar, text="")
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

        content = tk.Frame(self.body_frame)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._content_frame = content

        self.toc_frame = tk.Frame(content, width=240)
        self.toc_tree = ttk.Treeview(self.toc_frame, show="tree")
        self.toc_tree.pack(fill=tk.BOTH, expand=True)
        self.toc_tree.bind("<<TreeviewSelect>>", self._on_toc_select)
        # not packed by default -- toggled via View > Table of Contents

        self.canvas = tk.Canvas(content, bg="gray80")
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self.root.bind("<Left>", lambda e: self.prev())
        self.root.bind("<Right>", lambda e: self.next())
        self.root.bind("<Prior>", lambda e: self.prev())
        self.root.bind("<Next>", lambda e: self.next())

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

        self._doc_view_built = True

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

    def _kb_first_page(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self.viewer.goto(0)
        self.render()

    def _kb_last_page(self, event=None):
        if self._typing_in_entry() or self.viewer is None:
            return
        self.viewer.goto(self.viewer.page_count - 1)
        self.render()

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
            self.toc_frame.pack(side=tk.LEFT, fill=tk.Y, before=self.canvas)
        else:
            self.toc_frame.pack_forget()

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
        self.render()

    # ------------------------------------------------------------------
    # opening / closing documents
    # ------------------------------------------------------------------
    def _open_document(self, path):
        if self.doc is not None:
            self.doc.close()

        self.path = path
        self.doc = fitz.open(path)
        self.viewer = Viewer(self.doc)
        self._pending_redactions = []
        self.mode = "view"
        self.search_state = search.SearchState()  # stale matches from a prior doc must not linger

        self._ensure_doc_view_widgets()
        if self.home_frame is not None:
            self.home_frame.destroy()
            self.home_frame = None
        self.body_frame.pack(fill=tk.BOTH, expand=True)

        self.root.title(self._title())
        self._refresh_outline()
        self.render()
        recent.add_recent(path)

    def do_close(self):
        if self.doc is None:
            return
        self.doc.close()
        self.doc = None
        self.viewer = None
        self.path = None
        self.body_frame.pack_forget()
        self._show_home_screen()

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
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.config(width=img.width, height=img.height)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)
        self._draw_search_highlights()
        pending_here = sum(1 for p, _ in self._pending_redactions if p == self.viewer.page_num)
        self.status.config(
            text=f"Page {self.viewer.page_num + 1}/{self.viewer.page_count}"
            f"  zoom {self.viewer.zoom:.2f}x"
            + (f"  ({pending_here} pending redaction)" if pending_here else "")
        )

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

    def next(self):
        if self.viewer is None:
            return
        self.viewer.next_page()
        self.render()

    def prev(self):
        if self.viewer is None:
            return
        self.viewer.prev_page()
        self.render()

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

    def _on_press(self, event):
        self._drag_start = (event.x, event.y)
        if self.mode == "forms":
            self._handle_form_click(event.x, event.y)
            self._drag_start = None
        elif self.mode == "textedit":
            self._handle_textedit_click(event.x, event.y)
            self._drag_start = None

    def _on_drag(self, event):
        if self._drag_start is None:
            return
        if self._drag_rect_id:
            self.canvas.delete(self._drag_rect_id)
        x0, y0 = self._drag_start
        self._drag_rect_id = self.canvas.create_rectangle(
            x0, y0, event.x, event.y, outline="red", width=2
        )

    def _on_release(self, event):
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        self._drag_start = None
        if self._drag_rect_id:
            self.canvas.delete(self._drag_rect_id)
            self._drag_rect_id = None
        rect = self._canvas_to_pdf_rect(x0, y0, event.x, event.y)
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
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        self._open_document(path)

    def save(self):
        if not self._require_doc():
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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    app = SlateApp(root, path)
    root.mainloop()
    if app.doc is not None:
        app.doc.close()


if __name__ == "__main__":
    main()
