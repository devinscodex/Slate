#!/usr/bin/env python3
"""Slate — entry point. Slice 1: render/view with nav + zoom."""
import sys
import tkinter as tk

import fitz  # PyMuPDF
from PIL import ImageTk

from viewer import Viewer

DEFAULT_FIXTURE = "tests/fixtures/basic3page.pdf"


class SlateApp:
    def __init__(self, root, path):
        self.root = root
        self.doc = fitz.open(path)
        self.viewer = Viewer(self.doc)
        self._tk_img = None  # keep a reference or Tkinter garbage-collects it

        root.title("Slate")

        toolbar = tk.Frame(root)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(toolbar, text="< Prev", command=self.prev).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Next >", command=self.next).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Zoom -", command=self.zoom_out).pack(side=tk.LEFT)
        tk.Button(toolbar, text="Zoom +", command=self.zoom_in).pack(side=tk.LEFT)
        self.status = tk.Label(toolbar, text="")
        self.status.pack(side=tk.RIGHT, padx=8)

        self.canvas = tk.Canvas(root, bg="gray80")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        root.bind("<Left>", lambda e: self.prev())
        root.bind("<Right>", lambda e: self.next())
        root.bind("<Prior>", lambda e: self.prev())  # Page Up
        root.bind("<Next>", lambda e: self.next())  # Page Down

        self.render()

    def render(self):
        img = self.viewer.render_page()
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.config(width=img.width, height=img.height)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)
        self.status.config(
            text=f"Page {self.viewer.page_num + 1}/{self.viewer.page_count}"
            f"  zoom {self.viewer.zoom:.2f}x"
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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    root = tk.Tk()
    app = SlateApp(root, path)
    root.mainloop()
    app.doc.close()


if __name__ == "__main__":
    main()
