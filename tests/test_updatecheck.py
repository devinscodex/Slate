import json
import urllib.error

import updatecheck


def test_parse_version_handles_plain_semver():
    assert updatecheck._parse_version("1.1.0") == (1, 1, 0)


def test_parse_version_strips_leading_v_and_trailing_suffix():
    assert updatecheck._parse_version("v1.2.0-beta") == (1, 2, 0)


def test_parse_version_pads_short_versions():
    assert updatecheck._parse_version("2") == (2, 0, 0)
    assert updatecheck._parse_version("2.5") == (2, 5, 0)


class _FakeResp:
    def __init__(self, text: str):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return self._text.encode("utf-8")


def _fake_github_release(tag: str, html_url: str = "https://github.com/devinscodex/slate/releases/tag/x"):
    return _FakeResp(json.dumps({"tag_name": tag, "html_url": html_url}))


def test_github_newer_release_reports_update_available(monkeypatch):
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _fake_github_release("v1.2.0"),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is True
    assert result["latest_version"] == "v1.2.0"
    assert result["url"] == "https://github.com/devinscodex/slate/releases/tag/x"


def test_github_same_version_reports_no_update(monkeypatch):
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _fake_github_release("v1.1.0"),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is False


def test_github_older_release_does_not_report_update(monkeypatch):
    """A pre-release/rollback tag published behind the running build must
    not falsely prompt to "update" to an older version."""
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _fake_github_release("v1.0.0"),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is False


def test_github_response_missing_tag_name_fails_soft(monkeypatch):
    monkeypatch.setattr(
        updatecheck.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp(json.dumps({"html_url": "https://example.com"})),
    )

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is False
    assert "tag_name" in result["error"]


def test_github_network_failure_with_no_fossil_configured_fails_soft(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", None)

    def raise_error(*a, **k):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", raise_error)

    result = updatecheck.check_for_update("1.1.0")  # must not raise
    assert result["checked"] is False
    assert "404" in result["error"]


def test_github_unexpected_exception_fails_soft(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", None)

    def raise_error(*a, **k):
        raise ValueError("something weird")

    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", raise_error)

    result = updatecheck.check_for_update("1.1.0")  # must not raise
    assert result["checked"] is False
    assert "something weird" in result["error"]


_FAKE_VERSION_PY = '''"""Slate's version."""

VERSION = "{v}"
'''


def test_falls_back_to_fossil_server_when_github_unreachable(monkeypatch):
    """GitHub down/unreachable (offline dev box, rate-limited, DNS
    failure) but a fossil server IS configured -- the check should still
    complete against that fallback rather than reporting "not checked"."""
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")

    def fake_urlopen(req, timeout=None):
        if "api.github.com" in req.full_url:
            raise urllib.error.URLError("name resolution failed")
        return _FakeResp(_FAKE_VERSION_PY.format(v="1.2.0"))

    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", fake_urlopen)

    result = updatecheck.check_for_update("1.1.0")
    assert result["checked"] is True
    assert result["update_available"] is True
    assert result["latest_version"] == "1.2.0"
    assert result["url"] == "http://fake-fossil:8080/timeline"


def test_both_github_and_fossil_unreachable_fails_soft(monkeypatch):
    monkeypatch.setattr(updatecheck, "SERVER_URL", "http://fake-fossil:8080")

    def raise_error(*a, **k):
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, None)

    monkeypatch.setattr(updatecheck.urllib.request, "urlopen", raise_error)

    result = updatecheck.check_for_update("1.1.0")  # must not raise
    assert result["checked"] is False
    assert "500" in result["error"]
