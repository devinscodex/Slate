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
    "Slate: view, annotate, merge/split, redact, sign, fill forms, and "
    "scan for sensitive content -- plus a gated text-editing mode for "
    "correcting body text on a case-by-case basis. Built from proven "
    "libraries (PyMuPDF, pikepdf, pyHanko), not a reimplemented PDF engine.\n\n"
    "A byproduct of Cairn, an AI development harness -- built to be the "
    "document reader/editor we always wanted. Adobe is bloated and "
    "predatory, Foxit is mediocre, Sumatra is nice but limited -- Slate "
    "is another free, open-source option, proof of how good FOSS can "
    "really be. Coming to GitHub soon."
)
