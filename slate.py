#!/usr/bin/env python3
"""Slate — entry point and UI integration (slice 8). Wires viewer,
redact, annotate, merge_split, forms, sign, security, io_pdf together
into one menu-driven app. Business logic lives in the per-feature
modules; this file is glue + Tkinter widgets only.
"""
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import fitz  # PyMuPDF
from PIL import ImageTk

import annotate
import forms
import io_pdf
import merge_split
import redact
import security
import sign
from viewer import Viewer

DEFAULT_FIXTURE = "tests/fixtures/basic3page.pdf"


class SlateApp:
    def __init__(self, root, path):
        self.root = root
        self.path = path
        self.doc = fitz.open(path)
        self.viewer = Viewer(self.doc)
        self._tk_img = None  # keep a reference or Tkinter garbage-collects it
        self.mode = "view"  # view | redact | annotate:<kind> | forms
        self._drag_start = None
        self._drag_rect_id = None
        self._pending_redactions = []  # [(page_num, fitz.Rect), ...]

        root.title(self._title())
        self._build_menu()

        toolbar = tk.Frame(root)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(toolbar, text="< Prev", command=self.prev).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Next >", command=self.next).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Zoom -", command=self.zoom_out).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Zoom +", command=self.zoom_in).pack(side=tk.LEFT)
        self.mode_label = tk.Label(toolbar, text="mode: view", fg="blue")
        self.mode_label.pack(side=tk.LEFT, padx=12)
        self.status = tk.Label(toolbar, text="")
        self.status.pack(side=tk.RIGHT, padx=8)

        self.canvas = tk.Canvas(root, bg="gray80")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        root.bind("<Left>", lambda e: self.prev())
        root.bind("<Right>", lambda e: self.next())
        root.bind("<Prior>", lambda e: self.prev())
        root.bind("<Next>", lambda e: self.next())

        self.render()

    # ------------------------------------------------------------------
    # menu
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open...", command=self.open_file)
        filem.add_command(label="Save", command=self.save)
        filem.add_command(label="Save As...", command=self.save_as)
        filem.add_separator()
        filem.add_command(label="Merge PDFs...", command=self.do_merge)
        filem.add_command(label="Split into pages...", command=self.do_split)
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
        editm.add_command(label="Back to View mode", command=lambda: self._set_mode("view"))
        menubar.add_cascade(label="Edit", menu=editm)

        self.root.config(menu=menubar)

    def _title(self):
        signed = " [SIGNED]" if sign.is_signed(self.path) else ""
        return f"Slate — {os.path.basename(self.path)}{signed}"

    def _set_mode(self, mode):
        self.mode = mode
        self.mode_label.config(text=f"mode: {mode}")

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
        pending_here = sum(1 for p, _ in self._pending_redactions if p == self.viewer.page_num)
        self.status.config(
            text=f"Page {self.viewer.page_num + 1}/{self.viewer.page_count}"
            f"  zoom {self.viewer.zoom:.2f}x"
            + (f"  ({pending_here} pending redaction)" if pending_here else "")
        )

    def next(self):
        self.viewer.next_page()
        self.render()

    def prev(self):
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
            self._pending_redactions.append((self.viewer.page_num, rect))
            messagebox.showinfo(
                "Redaction marked",
                f"Region marked on page {self.viewer.page_num + 1}. Nothing is "
                "removed yet -- use Edit > Apply pending redactions to finish.",
            )
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
        self.doc.close()
        self.path = path
        self.doc = fitz.open(path)
        self.viewer = Viewer(self.doc)
        self._pending_redactions = []
        self.root.title(self._title())
        self.render()

    def save(self):
        io_pdf.backup_before_write(self.path)
        io_pdf.safe_save(self.doc, self.path)
        messagebox.showinfo("Saved", f"Saved to {self.path}")

    def save_as(self):
        out = filedialog.asksaveasfilename(defaultextension=".pdf")
        if not out:
            return
        io_pdf.safe_save(self.doc, out)
        messagebox.showinfo("Saved", f"Saved to {out}")

    def apply_redactions(self):
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
        self.doc.close()
        self.path = out
        self.doc = fitz.open(out)
        self.viewer = Viewer(self.doc)
        self.render()

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
        out_dir = filedialog.askdirectory(title="Choose output directory")
        if not out_dir:
            return
        parts = merge_split.split_pdf(self.doc)
        base = os.path.splitext(os.path.basename(self.path))[0]
        for i, part in enumerate(parts):
            io_pdf.safe_save(part, os.path.join(out_dir, f"{base}_p{i + 1}.pdf"))
            part.close()
        messagebox.showinfo("Split", f"Wrote {len(parts)} single-page files to {out_dir}")

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
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    root = tk.Tk()
    app = SlateApp(root, path)
    root.mainloop()
    app.doc.close()


if __name__ == "__main__":
    main()
