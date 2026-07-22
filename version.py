"""Slate's version -- bumped manually on each notable release, not
computed from anything (fossil hash, build timestamp) that wouldn't
exist on a deployed end-user machine without fossil/git installed.
"Rolling" here means monotonic release markers, not auto-generated.
"""

AUTHOR = "Devin Dwight"

VERSION = "1.1.0"
# 1.0.0 -- v1 core: view, annotate, merge/split, redact, sign, forms, scan
# 1.1.0 -- gated text editing (all 4 slices: fontmatch, textedit, gate, UI)

SUMMARY = (
    "Slate is a suckless PDF editor: view, annotate, merge/split, redact, "
    "sign, fill forms, and scan for sensitive content -- plus a gated "
    "text-editing mode for correcting body text on a case-by-case basis. "
    "Composed from proven libraries (PyMuPDF, pikepdf, pyHanko), not a "
    "reimplemented PDF engine."
)
