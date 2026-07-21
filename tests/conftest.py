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
gate.py's unlock.json shares the same ~/.slate/ directory and the same
risk (a stray test-set passphrase would otherwise land in real local
config), so it's isolated here too, pre-emptively.
"""
import pytest

import gate
import recent


@pytest.fixture(autouse=True)
def isolate_recent_files_storage(tmp_path, monkeypatch):
    cfg = tmp_path / ".slate-test-isolation"
    monkeypatch.setattr(recent, "CONFIG_DIR", cfg)
    monkeypatch.setattr(recent, "RECENT_FILE", cfg / "recent.json")
    monkeypatch.setattr(gate, "CONFIG_DIR", cfg)
    monkeypatch.setattr(gate, "UNLOCK_FILE", cfg / "unlock.json")
