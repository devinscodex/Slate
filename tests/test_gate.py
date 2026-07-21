"""Slice 3 check: passphrase set/check for the gated text-edit feature.
Storage isolation for gate.py's unlock.json comes from the autouse
fixture in conftest.py -- same pattern already used for recent.py.
"""
import gate


def test_is_passphrase_set_false_before_any_set():
    assert gate.is_passphrase_set() is False


def test_set_then_check_correct_passphrase_unlocks():
    gate.set_passphrase("hunter2")
    assert gate.is_passphrase_set() is True
    assert gate.check_passphrase("hunter2") is True


def test_wrong_passphrase_does_not_unlock():
    gate.set_passphrase("hunter2")
    assert gate.check_passphrase("wrong-guess") is False


def test_check_before_any_set_returns_false_not_error():
    # no is_passphrase_set() guard applied here on purpose -- must fail
    # closed, not raise, if a caller checks before the gate exists yet
    assert gate.check_passphrase("anything") is False


def test_passphrase_is_not_stored_in_plaintext_on_disk():
    gate.set_passphrase("hunter2")
    raw = gate.UNLOCK_FILE.read_text()
    assert "hunter2" not in raw


def test_resetting_the_passphrase_invalidates_the_old_one():
    gate.set_passphrase("first-pass")
    gate.set_passphrase("second-pass")
    assert gate.check_passphrase("first-pass") is False
    assert gate.check_passphrase("second-pass") is True
