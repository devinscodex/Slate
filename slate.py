#!/usr/bin/env python3
"""Slate — entry point. Slice 0: open a PDF, prove the window and page count work."""
import sys
import tkinter as tk

import fitz  # PyMuPDF

DEFAULT_FIXTURE = "tests/fixtures/basic3page.pdf"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    doc = fitz.open(path)
    page_count = doc.page_count

    root = tk.Tk()
    root.title("Slate")
    tk.Label(
        root,
        text=f"{path}\n{page_count} page(s)",
        font=("TkDefaultFont", 14),
        padx=40,
        pady=40,
    ).pack()
    root.mainloop()

    doc.close()


if __name__ == "__main__":
    main()
