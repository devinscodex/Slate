"""Slice 1 check: find_system_font correctly finds a font confirmed
present, and correctly returns None for one confirmed absent -- the
real, live-confirmed fc-match substitution pitfall (fc-match NEVER
fails, it always substitutes a "closest" font) is exactly what the
absent-font test guards against.

Real cross-platform bug caught running this suite on an actual Windows
box (not assumed): these tests originally hardcoded "DejaVu Sans" as
the example present font and "Calibri"/"Segoe UI" as example absent
fonts -- both Linux-specific assumptions. Calibri and Segoe UI are
real default Windows fonts, so "confirmed absent" was simply false
there, and DejaVu Sans isn't a default Windows font at all. Fixed by
resolving a real present-font name per platform instead of hardcoding
one -- the actual logic under test (fc-match's substitution pitfall,
winreg's HKCU/HKLM/normalization handling) is identical either way.
"""
import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fontmatch  # noqa: E402

# A font genuinely present by default on this platform, used as the
# "confirmed present" example -- resolved per-platform rather than
# hardcoded, since no single name is a safe default everywhere.
_A_REAL_FONT = "Arial" if platform.system() == "Windows" else "DejaVu Sans"
_A_FAKE_FONT = "Totally Fake Font XYZ123 Does Not Exist"  # safe "confirmed absent" on any platform


def test_normalize_font_name_strips_registry_and_postscript_conventions():
    # Windows registry display style
    assert fontmatch._normalize_font_name("Arial (TrueType)") == "arial"
    assert fontmatch._normalize_font_name("Arial Bold (TrueType)") == "arialbold"
    # PDF PostScript-name style
    assert fontmatch._normalize_font_name("ArialMT") == "arial"
    assert fontmatch._normalize_font_name("Arial-BoldMT") == "arialbold"
    assert fontmatch._normalize_font_name("TimesNewRomanPSMT") == "timesnewroman"
    # both forms of the same font must match each other
    assert fontmatch._normalize_font_name("Arial (TrueType)") == fontmatch._normalize_font_name(
        "ArialMT"
    )


def test_find_system_font_finds_a_font_confirmed_present():
    path = fontmatch.find_system_font(_A_REAL_FONT)
    assert path is not None
    assert os.path.exists(path)


def test_find_system_font_returns_none_for_a_font_confirmed_absent():
    """The real regression target on Linux: fc-match "Calibri" on a box
    with no Calibri installed returns "DejaVu Sans" with exit code 0
    and no error -- a naive "did fc-match succeed" check would wrongly
    report it as found. Using a name that cannot exist anywhere,
    rather than a specific real font that happens to be absent on one
    platform but present on another (the original bug this docstring
    now documents)."""
    assert fontmatch.find_system_font(_A_FAKE_FONT) is None


def test_verify_font_file_rejects_a_real_file_with_the_wrong_name():
    real_font_path = fontmatch.find_system_font(_A_REAL_FONT)
    assert real_font_path is not None
    assert fontmatch._verify_font_file(real_font_path, _A_FAKE_FONT) is False
    assert fontmatch._verify_font_file(real_font_path, _A_REAL_FONT) is True


def test_find_on_windows_logic_with_injected_registry_entries():
    """Real winreg I/O only runs on actual Windows -- but the matching/
    normalization LOGIC around it is platform-independent and testable
    via injection everywhere. Uses a real font file path (whichever
    platform this runs on) as the "Windows registry value data" so
    _verify_font_file's real fitz.Font check still runs against real
    bytes, not a mock -- this exercises _find_on_windows's own code
    directly regardless of what OS is actually running the test."""
    real_font_path = fontmatch.find_system_font(_A_REAL_FONT)
    fake_registry = [
        ("Not The Right Font (TrueType)", "notit.ttf"),  # won't match
        (f"{_A_REAL_FONT} (TrueType)", real_font_path),  # the one we're looking for
    ]
    found = fontmatch._find_on_windows(_A_REAL_FONT, registry_entries=iter(fake_registry))
    assert found == real_font_path


def test_find_on_windows_returns_none_when_not_in_registry():
    fake_registry = [("Not The Right Font (TrueType)", "notit.ttf")]
    found = fontmatch._find_on_windows(_A_FAKE_FONT, registry_entries=iter(fake_registry))
    assert found is None
