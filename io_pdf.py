"""Shared open/save. The hardened save path is the trust boundary for
redaction (see DESIGN.md) -- there is deliberately no "fast save" option
that skips garbage collection or forces an incremental write.
"""
import os
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


def replace_file(doc: fitz.Document, path: str) -> fitz.Document:
    """Hardened save over the file doc was opened from. MuPDF refuses an
    in-place full rewrite, and a crash during a direct write would corrupt
    the only copy, so write a sibling temp file, flush it to disk, then
    swap it in with os.replace.

    The edited state is held in memory across the swap. On success the
    result is reopened from path (no file handle kept on bytes); if the
    swap fails the in-memory document is returned so no edit is lost, and
    the error is re-raised after attaching it as `.live_doc`. doc is
    closed either way."""
    tmp = path + ".slate-tmp"
    try:
        safe_save(doc, tmp)
        with open(tmp, "rb") as f:
            data = f.read()
            os.fsync(f.fileno())
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    held = fitz.open("pdf", data)
    doc.close()
    try:
        os.replace(tmp, path)
    except OSError as err:
        if os.path.exists(tmp):
            os.remove(tmp)
        err.live_doc = held
        raise
    held.close()
    return fitz.open(path)
