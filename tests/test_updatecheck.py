import urllib.error

import pytest

import updatecheck


def test_parse_version_handles_plain_semver():
    assert updatecheck._parse_version("1.1.0") == (1, 1, 0)


def test_parse_version_strips_leading_v_and_trailing_suffix():
    assert updatecheck._parse_version("v1.2.0-beta") == (1, 2, 0)


def test_parse_version_pads_short_versions():
    assert updatecheck._parse_version("2") == (2, 0, 0)
    assert updatecheck._parse_version("2.5") == (2, 5, 0)


def test_no_server_configured_reports_not_checked_without_crashing(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", None)
    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is False
    assert result["update_available"] is False
    assert "configured" in result["error"].lower()


class _FakeResp:
    def __init__(self, text: str):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return self._text.encode("utf-8")


_FAKE_VERSION_PY = '''"""Slate's version."""

AUTHOR = "Devin Dwight"

VERSION = "{v}"

SUMMARY = "whatever"
'''


def test_newer_release_reports_update_available(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp(_FAKE_VERSION_PY.format(v="1.2.0")),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is True
    assert result["latest_version"] == "1.2.0"
    assert result["url"] == "http://fake-fossil:8080/timeline"


def test_same_version_reports_no_update(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp(_FAKE_VERSION_PY.format(v="1.1.0")),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is False


def test_older_trunk_version_does_not_report_update(monkeypatch):
    """Real edge case: trunk could be mid-development with an older
    version than a released build -- must not falsely prompt to
    'update' to an older version."""
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp(_FAKE_VERSION_PY.format(v="1.0.0")),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is False


def test_unexpected_file_format_fails_soft(monkeypatch):
    """Server reachable but the response doesn't look like version.py
    at all (wrong path resolved, server misconfigured, etc.)."""
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp("<html>not a python file</html>"),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is False
    assert "not found" in result["error"].lower()


def test_network_failure_fails_soft_never_raises(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")

    def raise_error(*a, **k):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", raise_error)

    result = updatecheck.check_for_update("1.1.0")  # must not raise
    assert result["checked"] is False
    assert "404" in result["error"]


def test_unexpected_exception_also_fails_soft(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")

    def raise_error(*a, **k):
        raise ValueError("something weird")

    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", raise_error)

    result = updatecheck.check_for_update("1.1.0")  # must not raise
    assert result["checked"] is False
    assert "something weird" in result["error"]
