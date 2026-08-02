"""Check a fossil server for a newer Slate version than the one
running. Real network call, real failure modes -- never raises, always
returns a plain result the caller can act on or ignore.

SERVER_URL is a placeholder until a reachable slate.fossil server
exists. check_for_update() reports "not configured" rather than
guessing a URL that would silently fail forever.

Mechanism: fossil's own `/raw/<file>?name=<branch>` HTTP endpoint
returns a file's raw content at a given check-in/branch tip -- fetch
version.py from trunk and parse VERSION out of it directly, no
separate release-tagging scheme needed.
"""
import re
import urllib.request
import urllib.error

SERVER_URL = None  # e.g. "http://100.119.73.83:PORT" -- set once a real slate.fossil server exists

_VERSION_RE = re.compile(r'VERSION\s*=\s*["\']([^"\']+)["\']')


def _parse_version(v: str):
    """"1.1.0" -> (1, 1, 0), tolerant of a leading 'v' and non-numeric
    trailing text (e.g. "1.2.0-beta")."""
    v = v.lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = ""
        for ch in p:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_for_update(current_version: str, timeout: float = 5.0) -> dict:
    """Returns a dict, always, never raises:
    {"checked": bool, "update_available": bool, "latest_version": str|None,
     "url": str|None, "error": str|None}
    "checked" False means the check itself didn't happen (no
    SERVER_URL configured, or a real network/parse failure) -- error
    names why.
    """
    if not SERVER_URL:
        return {
            "checked": False, "update_available": False,
            "latest_version": None, "url": None,
            "error": "Update checking isn't configured yet (no Slate fossil server set up).",
        }
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/raw/version.py?name=trunk",
            headers={"User-Agent": "Slate-update-check"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        match = _VERSION_RE.search(text)
        if not match:
            return {
                "checked": False, "update_available": False,
                "latest_version": None, "url": None,
                "error": "Fossil server reached but VERSION not found in version.py -- unexpected format.",
            }
        latest = match.group(1)
        is_newer = _parse_version(latest) > _parse_version(current_version)
        return {
            "checked": True, "update_available": is_newer,
            "latest_version": latest, "url": f"{SERVER_URL}/timeline", "error": None,
        }
    except urllib.error.HTTPError as e:
        return {
            "checked": False, "update_available": False,
            "latest_version": None, "url": None,
            "error": f"Fossil server returned {e.code}.",
        }
    except Exception as e:
        return {
            "checked": False, "update_available": False,
            "latest_version": None, "url": None,
            "error": f"Update check failed: {e}",
        }
