"""Autouse fixture: isolate recent.py's and gate.py's storage for EVERY
test in the suite, not just the ones that explicitly assert on it.

Real bug caught live during development: only the tests that directly
asserted on recent-files behavior monkeypatched recent.CONFIG_DIR/
RECENT_FILE. Every other integration test that opens a document via
SlateApp also calls recent.add_recent() as a side effect (that's the
whole point of the feature) -- and every one of those tests was quietly
writing real tmp-path test fixtures into the actual ~/.slate/recent.json
on the machine running the tests, polluting real local config with test
artifacts. Caught by literally looking at Slate's home screen after a
test run and seeing pytest tmp-dir paths in the "recently viewed" list.
gate.py's unlock.json, theme.py's theme.json, and tts.py's downloaded-
voices cache all share the same ~/.slate/ directory and the same risk
(a stray test download/preference/passphrase would otherwise land in
real local config), so all are isolated here too, pre-emptively.

Real bug caught on an actual Windows smoke test, a different flavor of
the same class of problem: tts._voice_cache (a module-level dict
caching loaded PiperVoice objects across calls, added as a real perf
fix) is never reset between tests either -- a test that downloads a
FAKE/invalid "alba" model and caches whatever (possibly broken) object
that produces can leave a later, unrelated test using the same voice_id
stuck reusing that broken cached object instead of loading a fresh
one, hanging deep inside onnxruntime on Windows specifically (ran fine
standalone; only hung as part of the full suite -- the tell that this
was cross-test contamination, not a real product bug).
"""
import pytest

import gate
import recent
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
    monkeypatch.setattr(tts, "DOWNLOADED_VOICES_DIR", cfg / "tts-voices")
    tts._voice_cache.clear()
