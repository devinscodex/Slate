"""theme.py's load/save preference round-trip. Storage isolation comes
from conftest.py's autouse fixture (same pattern as recent.py/gate.py).
Assertions check against theme.DEFAULT_THEME rather than a hardcoded
name, since Devin changed the default from "light" to "dark" already
once -- these should keep passing the next time that changes too.
"""
import theme


def test_load_preference_defaults_to_the_default_theme_when_nothing_saved():
    assert theme.load_preference() == theme.DEFAULT_THEME


def test_save_then_load_preference_round_trips():
    theme.save_preference("light")
    assert theme.load_preference() == "light"
    theme.save_preference("mosscairn_dark")
    assert theme.load_preference() == "mosscairn_dark"


def test_load_preference_corrupt_file_defaults_to_default_theme_not_an_error():
    theme.PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    theme.PREF_FILE.write_text("not valid json{{{")
    assert theme.load_preference() == theme.DEFAULT_THEME


def test_load_preference_unrecognized_theme_name_defaults_to_default_theme():
    """A saved preference naming a theme that no longer exists (e.g. an
    old config from before a theme was renamed/removed) must fail back
    to the default, not crash or silently apply garbage colors."""
    theme.save_preference("a-theme-that-does-not-exist")
    assert theme.load_preference() == theme.DEFAULT_THEME
