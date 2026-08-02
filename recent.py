"""Recently-viewed files, for the home screen (SumatraPDF-style). Local
JSON file only -- no database, no new dependency (plain `json`, stdlib).
"""
import json
import os
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
RECENT_FILE = CONFIG_DIR / "recent.json"
MAX_ENTRIES = 10


def _load() -> list:
    if not RECENT_FILE.exists():
        return []
    try:
        return json.loads(RECENT_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(json.dumps(entries, indent=2))


def add_recent(path: str):
    """Move-to-front if already present, else insert at front. Caps at
    MAX_ENTRIES -- the oldest entry drops off, not silently kept forever."""
    abspath = os.path.abspath(path)
    entries = [e for e in _load() if e.get("path") != abspath]
    entries.insert(0, {"path": abspath, "last_opened": time.time()})
    _save(entries[:MAX_ENTRIES])


def remove_recent(path: str):
    """Drop one entry by path. Compares by abspath, same normalization
    add_recent uses, so a relative/absolute mismatch can't leave a stale
    duplicate behind."""
    abspath = os.path.abspath(path)
    entries = [e for e in _load() if e.get("path") != abspath]
    _save(entries)


def get_recent(limit=MAX_ENTRIES) -> list:
    """Most-recent-first. Entries whose file no longer exists on disk are
    dropped silently -- a dead link in a recent-files list is worse than
    no entry at all, and re-saving here also self-heals the stored list."""
    entries = _load()
    live = [e for e in entries if os.path.exists(e.get("path", ""))]
    if len(live) != len(entries):
        _save(live)
    return live[:limit]
