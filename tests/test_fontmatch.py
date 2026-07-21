"""Slice 1 check: find_system_font correctly finds a font confirmed
present, and correctly returns None for one confirmed absent -- the
real, live-confirmed fc-match substitution pitfall (fc-match NEVER
fails, it always substitutes a "closest" font) is exactly what the
absent-font test guards against.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fontmatch  # noqa: E402


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


def test_find_system_font_finds_a_font_confirmed_present_via_fc_list():
    # DejaVu Sans ships on essentially every Linux desktop/CI image;
    # confirmed present on this dev box via `fc-list` before writing
    # this test, not assumed.
    path = fontmatch.find_system_font("DejaVu Sans")
    assert path is not None
    assert os.path.exists(path)


def test_find_system_font_returns_none_for_a_font_confirmed_absent():
    """The real regression target: fc-match "Calibri" on this box
    (no Calibri installed, confirmed via fc-list) returns "DejaVu Sans"
    with exit code 0 and no error -- a naive "did fc-match succeed"
    check would wrongly report Calibri as found. This must return None."""
    assert fontmatch.find_system_font("Calibri") is None
    assert fontmatch.find_system_font("Segoe UI") is None


def test_verify_font_file_rejects_a_real_file_with_the_wrong_name():
    dejavu = fontmatch.find_system_font("DejaVu Sans")
    assert dejavu is not None
    # DejaVu Sans's own file must not verify as "Calibri"
    assert fontmatch._verify_font_file(dejavu, "Calibri") is False
    assert fontmatch._verify_font_file(dejavu, "DejaVu Sans") is True


def test_find_on_windows_logic_with_injected_registry_entries():
    """Real winreg I/O isn't testable on this Linux dev box (winreg
    doesn't exist here at all) -- but the matching/normalization LOGIC
    around it is platform-independent and testable via injection.
    Uses a real font file path (DejaVu Sans) as the "Windows registry
    value data" so _verify_font_file's real fitz.Font check still runs
    against real bytes, not a mock."""
    dejavu_path = fontmatch.find_system_font("DejaVu Sans")
    fake_registry = [
        ("Arial (TrueType)", "arial.ttf"),  # a normal Windows-style entry, won't match
        ("DejaVu Sans (TrueType)", dejavu_path),  # the one we're looking for
    ]
    found = fontmatch._find_on_windows("DejaVu Sans", registry_entries=iter(fake_registry))
    assert found == dejavu_path


def test_find_on_windows_returns_none_when_not_in_registry():
    fake_registry = [("Arial (TrueType)", "arial.ttf")]
    found = fontmatch._find_on_windows("Calibri", registry_entries=iter(fake_registry))
    assert found is None
