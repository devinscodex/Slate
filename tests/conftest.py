"""Autouse fixture: isolate recent.py's and gate.py's storage for EVERY
test in the suite, not just the ones that explicitly assert on it.

Only the tests that directly asserted on recent-files behavior
monkeypatched recent.CONFIG_DIR/RECENT_FILE would otherwise be safe --
every other integration test that opens a document via SlateApp also
calls recent.add_recent() as a side effect (that's the whole point of
the feature), which without this fixture would quietly write real
tmp-path test fixtures into the actual ~/.slate/recent.json on the
machine running the tests, polluting real local config with test
artifacts. gate.py's unlock.json, theme.py's theme.json, and tts.py's
downloaded-voices cache all share the same ~/.slate/ directory and the
same risk (a stray test download/preference/passphrase would otherwise
land in real local config), so all are isolated here too, pre-emptively.

settings.py's settings.json carries this exact same risk (a test run
can leave a dead pytest tmp-path in the actual ~/.slate/settings.json's
open_tabs, and leave continuous_scroll/side_by_side however the last
test happened to set them) -- same fixture, same fix, no new pattern
needed.

tts._voice_cache (a module-level dict caching loaded PiperVoice objects
across calls, added as a real perf fix) is never reset between tests
either -- a test that downloads a FAKE/invalid "alba" model and caches
whatever (possibly broken) object that produces can leave a later,
unrelated test using the same voice_id stuck reusing that broken
cached object instead of loading a fresh one, hanging deep inside
onnxruntime on Windows specifically (a cross-test contamination bug,
not a real product bug -- runs fine standalone, only hangs as part of
the full suite).

theme.THEMES/THEME_LABELS/_chrome_overrides are also module-level and
mutated IN PLACE by save_as_new_theme/update_live/reload_from_disk (by
design -- a live color editor needs the running app's real dicts to
change under it, no separate "preview" copy). A test that calls any of
those (or exercises the color editor through SlateApp) would otherwise
leave a custom theme, a THEME_LABELS entry, or a cascade override
sitting in the shared module dict for every later test in the same
process -- exactly the kind of cross-test contamination this file
already guards against for tts._voice_cache above. Snapshotting and
restoring both dicts plus clearing overrides after every test closes
that gap the same way.

theme._THEME_DATA_DIR and theme._DEVS_THEMES_PALETTES are a REAL, live
version of that same gap, caught only by actually finding the damage on
disk after a test run (not proactively): save_family_values()/
reload_from_disk() read/write those two paths directly, and neither was
in the isolation list above -- test_theme_editor.py's own override-
round-trip tests wrote a genuine `slate_chrome_overrides` key straight
into the real, fossil-tracked `theme_data/bonepaper.json` (and its
sibling in the neighboring devs-themes checkout), silently, on a normal
test run. Copying the real theme_data/*.json into the isolated tmp dir
and pointing both module paths at copies closes this for good -- every
theme-family file a test could plausibly touch is covered, not just the
one that happened to get caught this time.
"""
import shutil

import pytest

import gate
import recent
import settings
import theme
import tts

_REAL_THEME_DATA_DIR = theme._THEME_DATA_DIR


@pytest.fixture(autouse=True)
def isolate_recent_files_storage(tmp_path, monkeypatch):
    cfg = tmp_path / ".slate-test-isolation"
    monkeypatch.setattr(recent, "CONFIG_DIR", cfg)
    monkeypatch.setattr(recent, "RECENT_FILE", cfg / "recent.json")
    monkeypatch.setattr(gate, "CONFIG_DIR", cfg)
    monkeypatch.setattr(gate, "UNLOCK_FILE", cfg / "unlock.json")
    monkeypatch.setattr(theme, "CONFIG_DIR", cfg)
    monkeypatch.setattr(theme, "PREF_FILE", cfg / "theme.json")
    monkeypatch.setattr(theme, "CUSTOM_THEMES_FILE", cfg / "custom_themes.json")
    # Real theme_data/*.json copied fresh into the isolated tmp dir each
    # test -- save_family_values()/reload_from_disk() are free to read
    # and write these like the real thing without ever touching the
    # actual fossil-tracked files (see this file's own module docstring
    # for the real incident that made this necessary). devs-themes gets
    # the identical copies at a separate path -- save_family_values()
    # writes both independently, both need to exist for a save to
    # succeed at all.
    fake_theme_data = cfg / "theme_data"
    fake_theme_data.mkdir(parents=True)
    fake_devs_palettes = cfg / "devs-themes-palettes"
    fake_devs_palettes.mkdir(parents=True)
    for f in _REAL_THEME_DATA_DIR.glob("*.json"):
        shutil.copy(f, fake_theme_data / f.name)
        shutil.copy(f, fake_devs_palettes / f.name)
    monkeypatch.setattr(theme, "_THEME_DATA_DIR", fake_theme_data)
    monkeypatch.setattr(theme, "_DEVS_THEMES_PALETTES", fake_devs_palettes)
    monkeypatch.setattr(settings, "CONFIG_DIR", cfg)
    monkeypatch.setattr(settings, "SETTINGS_FILE", cfg / "settings.json")
    monkeypatch.setattr(tts, "DOWNLOADED_VOICES_DIR", cfg / "tts-voices")
    tts._voice_cache.clear()
    _themes_snapshot = dict(theme.THEMES)
    _labels_snapshot = dict(theme.THEME_LABELS)
    yield
    theme.THEMES.clear()
    theme.THEMES.update(_themes_snapshot)
    theme.THEME_LABELS.clear()
    theme.THEME_LABELS.update(_labels_snapshot)
    theme._chrome_overrides.clear()
