"""Edit Colors dialog's underlying theme.py machinery: editing/overriding
a built-in theme's cascade-derived colors, and saving/loading/reloading
a whole new user-created custom theme. Storage isolation (CUSTOM_THEMES_FILE,
CONFIG_DIR, plus THEMES/THEME_LABELS/_chrome_overrides snapshot-restore)
comes from conftest.py's autouse fixture, same pattern as theme_persistence.
"""
import pytest

import theme


def test_is_custom_true_only_for_a_saved_theme_not_any_built_in_family():
    for name in theme.THEMES:
        assert theme.is_custom(name) is False, name
    assert theme.is_custom("not-a-real-theme") is True


def test_update_live_on_a_base_key_still_recomputes_the_cascade_as_before():
    theme.update_live("slate_light", "bg", "#123456")
    assert theme.THEMES["slate_light"]["bg"] == "#123456"
    assert theme.THEMES["slate_light"]["menubar_bg"] == "#123456"  # menubar_bg = bg


def test_update_live_on_a_cascade_key_directly_overrides_it():
    theme.update_live("slate_light", "menubar_bg", "#ff00ff")
    assert theme.THEMES["slate_light"]["menubar_bg"] == "#ff00ff"


def test_cascade_override_survives_a_later_base_key_edit():
    """The real point of _chrome_overrides: once a derived color is
    hand-set, changing an unrelated base color must not silently discard
    it -- that's the whole reason update_live tracks overrides instead
    of just letting _with_chrome_cascade's formula win again."""
    theme.update_live("slate_light", "menubar_bg", "#ff00ff")
    theme.update_live("slate_light", "fg", "#000001")  # unrelated base edit
    assert theme.THEMES["slate_light"]["menubar_bg"] == "#ff00ff"  # still overridden
    assert theme.THEMES["slate_light"]["fg"] == "#000001"  # the actual edit landed


def test_update_live_rejects_an_unknown_key_on_a_built_in_theme():
    with pytest.raises(ValueError):
        theme.update_live("slate_light", "not_a_real_key", "#000000")


def test_update_live_on_a_custom_theme_accepts_any_existing_key_flatly():
    key = theme.save_as_new_theme("slate_light", "Test Blend")
    theme.update_live(key, "menubar_bg", "#abcdef")  # a cascade key, but no formula to protect
    assert theme.THEMES[key]["menubar_bg"] == "#abcdef"
    with pytest.raises(ValueError):
        theme.update_live(key, "not_a_real_key", "#000000")


def test_save_family_values_round_trips_a_cascade_override_through_reload():
    theme.update_live("slate_light", "menubar_bg", "#ff00ff")
    theme.save_family_values("slate_light")
    theme.update_live("slate_light", "menubar_bg", "#000000")  # clobber in-memory
    theme.reload_from_disk("slate_light")
    assert theme.THEMES["slate_light"]["menubar_bg"] == "#ff00ff"  # restored from disk


def test_save_family_values_removes_a_since_cleared_override_from_disk():
    theme.update_live("slate_light", "menubar_bg", "#ff00ff")
    theme.save_family_values("slate_light")
    theme.reload_from_disk("slate_light")  # picks the override back up in-memory
    theme._chrome_overrides.pop("slate_light")  # simulate the override being cleared
    theme.save_family_values("slate_light")
    theme.reload_from_disk("slate_light")
    assert theme.THEMES["slate_light"]["menubar_bg"] == theme.THEMES["slate_light"]["bg"]  # back to formula


def test_load_saved_chrome_overrides_restores_every_built_in_theme():
    theme.update_live("bonepaper_dark", "toolbar_fg", "#112233")
    theme.save_family_values("bonepaper_dark")
    theme._chrome_overrides.clear()  # simulate a fresh process
    theme.load_saved_chrome_overrides()
    assert theme.THEMES["bonepaper_dark"]["toolbar_fg"] == "#112233"


def test_save_as_new_theme_snapshots_the_live_palette_under_a_new_key():
    theme.update_live("slate_dark", "bg", "#0a0a0a")
    key = theme.save_as_new_theme("slate_dark", "Devin's Blend")
    assert theme.THEMES[key]["bg"] == "#0a0a0a"
    assert theme.THEMES[key] == theme.THEMES["slate_dark"]  # full snapshot, not a partial copy
    assert key != "slate_dark"  # source untouched/unaliased
    assert theme.THEME_LABELS["Devin's Blend Dark"] == key


def test_save_as_new_theme_mode_suffix_matches_the_source_is_dark():
    light_key = theme.save_as_new_theme("slate_light", "Foo")
    dark_key = theme.save_as_new_theme("slate_dark", "Foo")
    assert "Foo Light" in theme.THEME_LABELS and theme.THEME_LABELS["Foo Light"] == light_key
    assert "Foo Dark" in theme.THEME_LABELS and theme.THEME_LABELS["Foo Dark"] == dark_key
    assert light_key != dark_key


def test_save_as_new_theme_rejects_empty_name():
    with pytest.raises(ValueError):
        theme.save_as_new_theme("slate_light", "   ")


def test_save_as_new_theme_rejects_a_label_that_already_exists():
    theme.save_as_new_theme("slate_light", "Dup")
    with pytest.raises(ValueError):
        theme.save_as_new_theme("slate_light", "Dup")


def test_save_as_new_theme_disambiguates_a_colliding_slug():
    """Two different display names that slugify to the same key (e.g.
    differing only in punctuation/case) must not silently collide and
    overwrite one another."""
    key1 = theme.save_as_new_theme("slate_light", "My Theme!")
    key2 = theme.save_as_new_theme("slate_dark", "my_theme")
    assert key1 != key2
    assert key1 in theme.THEMES and key2 in theme.THEMES


def test_new_custom_theme_persists_to_disk_and_survives_reload():
    key = theme.save_as_new_theme("slate_light", "Persisted")
    assert theme.CUSTOM_THEMES_FILE.exists()
    theme.THEMES.pop(key)
    theme.THEME_LABELS.pop("Persisted Light")
    theme.load_custom_themes()
    assert key in theme.THEMES
    assert theme.THEME_LABELS["Persisted Light"] == key


def test_load_custom_themes_is_a_silent_no_op_with_no_saved_file():
    before_themes, before_labels = dict(theme.THEMES), dict(theme.THEME_LABELS)
    theme.load_custom_themes()
    assert theme.THEMES == before_themes
    assert theme.THEME_LABELS == before_labels


def test_load_custom_themes_tolerates_a_corrupt_file():
    theme.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    theme.CUSTOM_THEMES_FILE.write_text("not valid json{{{")
    theme.load_custom_themes()  # must not raise


def test_save_custom_theme_persists_further_edits_to_an_already_custom_theme():
    key = theme.save_as_new_theme("slate_light", "Editable")
    theme.update_live(key, "bg", "#010101")
    theme.save_custom_theme(key)
    theme.THEMES[key] = dict(theme.THEMES[key]) | {"bg": "#ffffff"}  # clobber in-memory only
    theme.reload_custom_theme(key)
    assert theme.THEMES[key]["bg"] == "#010101"  # restored from disk, not the clobbered value


def test_save_custom_theme_rejects_a_built_in_theme_name():
    with pytest.raises(ValueError):
        theme.save_custom_theme("slate_light")


def test_reload_custom_theme_raises_for_an_unknown_theme():
    with pytest.raises(KeyError):
        theme.reload_custom_theme("never-saved")
