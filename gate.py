"""Local passphrase gate for the text-edit feature (DESIGN.md's "Text
editing" section) -- a UX gate so text editing isn't a plain menu item
everyone gets, NOT real access control. Anyone with the source/binary
can bypass this; stated plainly, an accepted tradeoff already implicit
in how the feature was scoped. stdlib only: hashlib.pbkdf2_hmac, no new
dependency. Same ~/.slate/ config convention as recent.py.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
UNLOCK_FILE = CONFIG_DIR / "unlock.json"
ITERATIONS = 600_000


def is_passphrase_set() -> bool:
    return UNLOCK_FILE.exists()


def set_passphrase(passphrase: str):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, ITERATIONS)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    UNLOCK_FILE.write_text(json.dumps({
        "salt": salt.hex(),
        "hash": digest.hex(),
        "iterations": ITERATIONS,
    }))


def check_passphrase(passphrase: str) -> bool:
    """False if no passphrase has ever been set -- callers must check
    is_passphrase_set() first and route to the set-passphrase flow
    instead of treating "no gate yet" as "any passphrase unlocks it"."""
    if not UNLOCK_FILE.exists():
        return False
    try:
        data = json.loads(UNLOCK_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    salt = bytes.fromhex(data["salt"])
    iterations = data.get("iterations", ITERATIONS)
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, bytes.fromhex(data["hash"]))
