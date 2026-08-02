"""Check for a newer Slate release than the one running. Real network
call, real failure modes -- never raises, always returns a plain result
the caller can act on or ignore.

GitHub releases is the primary source (the repo is public and always
reachable, no infra to stand up). A fossil server is a secondary,
opt-in source for anyone running Slate off a private fossil mirror
instead of the GitHub build -- SERVER_URL stays None until one exists,
and is only consulted if the GitHub check itself couldn't complete
(network failure), not merely because it found no update.
"""
import json
import re
import urllib.request
import urllib.error

GITHUB_REPO = "devinscodex/slate"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

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


def _result(checked, update_available=False, latest_version=None, url=None, error=None):
    return {
        "checked": checked, "update_available": update_available,
        "latest_version": latest_version, "url": url, "error": error,
    }


def _check_github_release(current_version: str, timeout: float) -> dict:
    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"User-Agent": "Slate-update-check", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    tag = data.get("tag_name")
    if not tag:
        return _result(False, error="GitHub API reached but the release has no tag_name -- unexpected format.")
    is_newer = _parse_version(tag) > _parse_version(current_version)
    return _result(
        True, update_available=is_newer, latest_version=tag,
        url=data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest"),
    )


def _check_fossil_server(current_version: str, timeout: float) -> dict:
    """Fossil's own `/raw/<file>?name=<branch>` HTTP endpoint returns a
    file's raw content at a given check-in/branch tip -- fetch
    version.py from trunk and parse VERSION out of it directly, no
    separate release-tagging scheme needed."""
    req = urllib.request.Request(
        f"{SERVER_URL}/raw/version.py?name=trunk",
        headers={"User-Agent": "Slate-update-check"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    match = _VERSION_RE.search(text)
    if not match:
        return _result(False, error="Fossil server reached but VERSION not found in version.py -- unexpected format.")
    latest = match.group(1)
    is_newer = _parse_version(latest) > _parse_version(current_version)
    return _result(True, update_available=is_newer, latest_version=latest, url=f"{SERVER_URL}/timeline")


def check_for_update(current_version: str, timeout: float = 5.0) -> dict:
    """Returns a dict, always, never raises:
    {"checked": bool, "update_available": bool, "latest_version": str|None,
     "url": str|None, "error": str|None}
    "checked" False means no source could complete the check -- error
    names why (the LAST error seen, if both sources were tried).
    """
    try:
        return _check_github_release(current_version, timeout)
    except urllib.error.HTTPError as e:
        github_error = f"GitHub returned {e.code}."
    except Exception as e:
        github_error = f"GitHub update check failed: {e}"

    if not SERVER_URL:
        return _result(False, error=github_error)

    try:
        return _check_fossil_server(current_version, timeout)
    except urllib.error.HTTPError as e:
        return _result(False, error=f"Fossil server returned {e.code}.")
    except Exception as e:
        return _result(False, error=f"Update check failed: {e}")
