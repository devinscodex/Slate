"""Downloads and applies a Slate update in place, using the asset list
updatecheck.check_for_update() already found on the GitHub release.

Windows-only -- the installer is an Inno Setup .exe, and PrivilegesRequired
=lowest in installer/slate.iss means it needs no elevation, so this never
has to deal with UAC. Non-Windows callers, or a release published
without both required assets, get told plainly to use the release page
instead; nothing here ever guesses an install path or runs anything
unverified.

Real network call, real failure modes -- every public function here
returns a plain result the caller can show the user, never raises.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

INSTALLER_NAME_RE = re.compile(r"^Slate-Setup-.*\.exe$")
SUMS_NAME = "SHA256SUMS.txt"

# A verified-downloaded installer the user deferred instead of running
# right away ("At Close"/"Next Startup" in slate.py's update-timing
# prompt). Same ~/.slate convention as theme.py/settings.py. Only
# "Next Startup" actually needs this written to disk ("At Close" just
# keeps the path in memory for this same process's own exit path) --
# but it's also the fallback main() reads at the top of every launch,
# so a path saved here is the one source of truth for "there's a
# verified installer waiting."
PENDING_FILE = Path.home() / ".slate" / "pending_update.json"


def find_installer_asset(assets):
    """assets: the list check_for_update() returns. Returns
    (installer_asset, sums_asset); either is None if that asset isn't
    in the release -- a release missing one is treated as unusable for
    self-update rather than attempted half-verified."""
    installer = next((a for a in assets if a.get("name") and INSTALLER_NAME_RE.match(a["name"])), None)
    sums = next((a for a in assets if a.get("name") == SUMS_NAME), None)
    return installer, sums


def _download(url: str, dest: str, timeout: float, on_progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Slate-self-update"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)


def _sha256sums_lookup(sums_text: str, filename: str):
    """SHA256SUMS.txt is sha256sum's own format: 'hex<space(s)>name'
    per line, name optionally '*'-prefixed for binary mode."""
    for line in sums_text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def download_and_verify(installer_asset, sums_asset, timeout: float = 30.0, on_progress=None):
    """Downloads SHA256SUMS.txt then the installer, verifies the
    installer's real hash against the manifest before trusting it.
    Returns (installer_path, error): error is None only on full
    success; installer_path is None on any failure so the caller can
    never accidentally run a partial or unverified file."""
    tmpdir = tempfile.mkdtemp(prefix="slate-update-")
    installer_path = os.path.join(tmpdir, installer_asset["name"])
    sums_path = os.path.join(tmpdir, SUMS_NAME)
    try:
        _download(sums_asset["download_url"], sums_path, timeout)
        with open(sums_path, encoding="utf-8") as f:
            expected = _sha256sums_lookup(f.read(), installer_asset["name"])
        if not expected:
            return None, f"{installer_asset['name']} is not listed in {SUMS_NAME} -- refusing to run an unverified installer."

        _download(installer_asset["download_url"], installer_path, timeout, on_progress)

        actual = hashlib.sha256()
        with open(installer_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                actual.update(chunk)
        if actual.hexdigest().lower() != expected:
            os.remove(installer_path)
            return None, "Downloaded installer failed checksum verification -- not running it."
        return installer_path, None
    except Exception as e:
        return None, f"Download failed: {e}"


def launch_installer_and_restart(installer_path: str, slate_exe: str) -> bool:
    """Runs the installer silently, then starts the freshly-installed
    Slate.exe once it finishes. The CALLER must save its own state and
    exit immediately after this returns True -- the installer needs
    Slate.exe to no longer be running to overwrite it, which is also
    why this can't just subprocess.run() the installer directly and
    wait: that would block on this very process's own exit. A detached
    cmd wrapper chains install-then-relaunch and outlives us instead.

    No /DIR passed to the installer -- same AppId as the current
    install (installer/slate.iss), so Inno Setup reuses the already-
    recorded install path from the registry rather than this code
    guessing one.

    Returns False (never raises) if the installer couldn't even be
    launched, leaving the current install untouched -- the caller
    reports that rather than exiting into neither version working.
    """
    if sys.platform != "win32":
        return False
    try:
        cmd = f'"{installer_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART && start "" "{slate_exe}"'
        subprocess.Popen(
            ["cmd", "/c", cmd],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def save_pending_update(installer_path: str):
    """Records a verified installer to install on the NEXT launch
    instead of now -- main() checks this at the very top, before any
    UI exists. Deliberately not used for the "At Close" choice, which
    just keeps installer_path in a slate.py instance attr for this
    same process's own exit (no reason to touch disk for something
    that never outlives this run)."""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({"installer_path": installer_path}))


def load_pending_update():
    """Returns the pending installer's path, or None -- also None (and
    silently clears the stale record) if the file it points to is
    gone, since a temp dir can be swept by the OS between sessions and
    nothing should ever try to run a path that no longer exists."""
    if not PENDING_FILE.exists():
        return None
    try:
        path = json.loads(PENDING_FILE.read_text()).get("installer_path")
    except (json.JSONDecodeError, OSError):
        path = None
    if not path or not os.path.exists(path):
        clear_pending_update()
        return None
    return path


def clear_pending_update():
    try:
        PENDING_FILE.unlink()
    except OSError:
        pass
