"""theme.py's load/save preference round-trip. Storage isolation comes
from conftest.py's autouse fixture (same pattern as recent.py/gate.py).
"""
import theme


def test_load_preference_defaults_to_light_when_nothing_saved():
    assert theme.load_preference() is False


def test_save_then_load_preference_round_trips():
    theme.save_preference(True)
    assert theme.load_preference() is True
    theme.save_preference(False)
    assert theme.load_preference() is False


def test_load_preference_corrupt_file_defaults_to_light_not_an_error():
    theme.PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    theme.PREF_FILE.write_text("not valid json{{{")
    assert theme.load_preference() is False
