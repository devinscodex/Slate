"""theme.py's load/save preference round-trip. Storage isolation comes
from conftest.py's autouse fixture (same pattern as recent.py/gate.py).
"""
import theme


def test_load_preference_defaults_to_light_when_nothing_saved():
    assert theme.load_preference() == "light"


def test_save_then_load_preference_round_trips():
    theme.save_preference("dark")
    assert theme.load_preference() == "dark"
    theme.save_preference("solarized_dark")
    assert theme.load_preference() == "solarized_dark"


def test_load_preference_corrupt_file_defaults_to_light_not_an_error():
    theme.PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    theme.PREF_FILE.write_text("not valid json{{{")
    assert theme.load_preference() == "light"


def test_load_preference_unrecognized_theme_name_defaults_to_light():
    """A saved preference naming a theme that no longer exists (e.g. an
    old config from before a theme was renamed/removed) must fail back
    to the default, not crash or silently apply garbage colors."""
    theme.save_preference("a-theme-that-does-not-exist")
    assert theme.load_preference() == "light"
