"""find_system_font(name) -- check whether a font is already installed
on THIS machine as a real system font, before falling back to a crude
Base-14 substitute. Zero new dependency: stdlib `winreg`/`ctypes` on
Windows, `subprocess` + fontconfig's CLI tools on Linux.

Real pitfall this module exists to avoid: `fc-match` NEVER fails -- it
always substitutes a "closest" font (e.g. `fc-match "Calibri"` on a box
with no Calibri returns "DejaVu Sans", exit code 0, no error). Any code
treating fc-match's success as "found" is wrong. Fix: compare the
*returned* family against what was asked for; a mismatch means
fontconfig substituted, not matched.

Windows registry lookup (`_find_on_windows`) follows Microsoft's
documented layout: HKEY_CURRENT_USER checked before HKEY_LOCAL_MACHINE
(per-user-installed fonts since Windows 10 1803 live in HKCU, missed if
only HKLM is checked) -- not exercised against a real Windows registry
in this dev environment (Linux). Name-normalization
(_normalize_font_name) is platform-independent and fully tested.
"""
import platform
import re
import subprocess

import fitz


def _normalize_font_name(name: str) -> str:
    """'Arial (TrueType)' and 'ArialMT' need to compare equal (same
    regular-weight font, two different naming conventions) -- but
    'Arial' and 'Arial Bold' must NOT compare equal, they're different
    font files. Only "Regular" (a redundant no-style marker some
    producers add) is stripped; Bold/Italic/Oblique are kept as
    meaningful, comparison-relevant content."""
    n = name
    n = re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", n, flags=re.I)
    n = re.sub(r"(MT|PS|PSMT)$", "", n)
    n = re.sub(r"[-_]?Regular$", "", n, flags=re.I)
    n = re.sub(r"[\s\-_]", "", n)
    return n.lower()


def _verify_font_file(path: str, expected_name: str) -> bool:
    """Open the candidate file directly and check its own internal name
    -- don't trust the registry/fontconfig string match alone. Uses
    PyMuPDF's Font.name, already a dependency, no new code needed."""
    try:
        real_name = fitz.Font(fontfile=path).name
    except Exception:
        return False
    if not real_name:
        return False
    return _normalize_font_name(real_name) == _normalize_font_name(expected_name) or (
        _normalize_font_name(expected_name) in _normalize_font_name(real_name)
    )


def _find_on_linux(name: str) -> str:
    """fc-match's own family output must equal what was asked for --
    fc-match's exit code and stdout are NOT a found/not-found signal by
    themselves, confirmed live (see module docstring)."""
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family}", name],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    returned_family = result.stdout.strip().split(",")[0]
    if _normalize_font_name(returned_family) != _normalize_font_name(name):
        return None  # fontconfig substituted, it did not match

    try:
        path_result = subprocess.run(
            ["fc-match", "--format=%{file}", name],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    path = path_result.stdout.strip()
    if not path:
        return None
    return path if _verify_font_file(path, name) else None


def _default_windows_registry_entries():
    """Real winreg enumeration -- HKEY_CURRENT_USER first (per-user-
    installed fonts, Windows 10 1803+, missed if only HKLM is checked),
    then HKEY_LOCAL_MACHINE. Imported lazily: `winreg` does not exist
    on non-Windows platforms at all, importing it at module level would
    break every test on this (Linux) dev box."""
    import winreg

    key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                i = 0
                while True:
                    try:
                        value_name, value_data, _ = winreg.EnumValue(key, i)
                        yield value_name, value_data
                        i += 1
                    except OSError:
                        break
        except FileNotFoundError:
            continue


def _find_on_windows(name: str, registry_entries=None) -> str:
    """registry_entries is injectable for testing (a real Windows
    registry isn't available in this dev environment) -- defaults to
    the real enumerator above. Each entry is (value_name, value_data)
    exactly as winreg.EnumValue returns."""
    import os

    if registry_entries is None:
        registry_entries = _default_windows_registry_entries()

    target = _normalize_font_name(name)
    for value_name, value_data in registry_entries:
        if _normalize_font_name(value_name) != target:
            continue
        path = value_data
        if not os.path.isabs(path):
            fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
            path = os.path.join(fonts_dir, path)
        if _verify_font_file(path, name):
            return path
    return None


def find_system_font(name: str, _registry_entries=None) -> str:
    """Returns a verified font file path, or None. `_registry_entries`
    is test-only (Windows path), ignored on Linux."""
    system = platform.system()
    if system == "Windows":
        return _find_on_windows(name, registry_entries=_registry_entries)
    return _find_on_linux(name)
