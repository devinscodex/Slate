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
    "Slate is the document reader and editor you've always wanted -- the "
    "commonsense things you already expect an app like this to do, without "
    "a subscription, a login, or a bloated installer in the way: view, "
    "annotate, merge/split, fill forms, sign, redact, scan for sensitive "
    "content, and a gated mode for correcting body text on a case-by-case "
    "basis. One reader for PDF, ebooks (EPUB/MOBI/FB2/CBZ), plain text, "
    "Markdown, HTML, images, and code -- no format tax.\n\n"
    "Built from proven libraries (PyMuPDF, pikepdf, pyHanko), not a "
    "reimplemented PDF engine.\n\n"
    "Standard's light/dark modes are Flexoki, Steph Ango's (Kepano, "
    "Obsidian's CEO) open-source palette (stephango.com/flexoki) -- one "
    "small nod, among several here, to his \"File Over App\" principle "
    "(stephango.com/file-over-app): your data should outlive any single "
    "piece of software. That's the same reason Slate works directly on "
    "real PDFs and plain files instead of some app-specific project "
    "format.\n\n"
    "Free and open-source. Coming to GitHub soon."
)
