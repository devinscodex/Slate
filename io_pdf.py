"""Shared open/save. The hardened save path is the trust boundary for
redaction (see DESIGN.md) -- there is deliberately no "fast save" option
that skips garbage collection or forces an incremental write.
"""
import shutil
from pathlib import Path

import fitz


def safe_save(doc: fitz.Document, path: str):
    """The only save path Slate exposes for documents that may have been
    redacted. Full rewrite (never incremental) + garbage-collect orphaned
    objects + clean content streams + drop metadata that isn't needed.

    incremental=False is the load-bearing setting: an incremental save
    keeps prior revisions' bytes in the file verbatim, so anything
    redacted out of the CURRENT revision would still be byte-recoverable
    from an earlier one. garbage=4 is the strongest PyMuPDF garbage-
    collection level (also merges duplicate objects).
    """
    doc.save(path, garbage=4, clean=True, incremental=False, deflate=True)


def unsafe_save_for_testing(doc: fitz.Document, path: str):
    """NEVER call this outside the redaction test harness. Deliberately
    skips garbage collection, to prove the safe path above is load-
    bearing and not decorative -- test_redact.py asserts this path
    leaves the canary recoverable, safe_save does not.
    """
    doc.save(path, incremental=False)


def backup_before_write(path: str) -> str:
    """Copy the original file to <path>.bak before any destructive
    operation. Slate must never overwrite the only copy of a document
    mid-edit -- a mis-click during redaction shouldn't be unrecoverable.
    Returns the backup path.
    """
    src = Path(path)
    if not src.exists():
        return ""
    backup = src.with_suffix(src.suffix + ".bak")
    shutil.copy2(src, backup)
    return str(backup)
