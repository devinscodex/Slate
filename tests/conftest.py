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
"""
import pytest

import gate
import recent
import settings
import theme
import tts


@pytest.fixture(autouse=True)
def isolate_recent_files_storage(tmp_path, monkeypatch):
    cfg = tmp_path / ".slate-test-isolation"
    monkeypatch.setattr(recent, "CONFIG_DIR", cfg)
    monkeypatch.setattr(recent, "RECENT_FILE", cfg / "recent.json")
    monkeypatch.setattr(gate, "CONFIG_DIR", cfg)
    monkeypatch.setattr(gate, "UNLOCK_FILE", cfg / "unlock.json")
    monkeypatch.setattr(theme, "CONFIG_DIR", cfg)
    monkeypatch.setattr(theme, "PREF_FILE", cfg / "theme.json")
    monkeypatch.setattr(settings, "CONFIG_DIR", cfg)
    monkeypatch.setattr(settings, "SETTINGS_FILE", cfg / "settings.json")
    monkeypatch.setattr(tts, "DOWNLOADED_VOICES_DIR", cfg / "tts-voices")
    tts._voice_cache.clear()
