"""Slate's version -- bumped manually on each notable release, not
computed from anything (fossil hash, build timestamp) that wouldn't
exist on a deployed end-user machine without fossil/git installed.
"Rolling" here means monotonic release markers, not auto-generated.
"""

AUTHOR = "devinscodex"

VERSION = "1.1.0"
# 1.0.0 -- v1 core: view, annotate, merge/split, redact, sign, forms, scan
# 1.1.0 -- gated text editing (all 4 slices: fontmatch, textedit, gate, UI)

SUMMARY = (
    "Slate is the document reader and editor you've always wanted: view, "
    "annotate, merge/split, fill forms, sign, redact, scan for sensitive "
    "content, and a gated mode for correcting body text -- no subscription, "
    "no login, no bloated installer. One reader for PDF, ebooks (EPUB/MOBI/"
    "FB2/CBZ), plain text, Markdown, HTML, images, and code. Built from "
    "proven libraries (PyMuPDF, pikepdf, pyHanko), not a reimplemented "
    "engine.\n\n"
    "Standard's light/dark modes are Flexoki, Steph Ango's (Kepano, "
    "Obsidian's CEO) open palette (stephango.com/flexoki) -- a nod to "
    "\"File Over App\" (stephango.com/file-over-app): data should outlive "
    "the software. Same reason Slate works on real files, not a "
    "project-specific format.\n\n"
    "Free and open-source. Coming to GitHub soon."
)
