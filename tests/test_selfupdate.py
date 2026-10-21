import hashlib
import http.server
import threading

import pytest

import selfupdate


def test_find_installer_asset_matches_installer_and_sums_by_name():
    assets = [
        {"name": "Slate-portable.zip", "download_url": "http://x/zip"},
        {"name": "Slate-Setup-1.7.6.exe", "download_url": "http://x/exe"},
        {"name": "SHA256SUMS.txt", "download_url": "http://x/sums"},
    ]
    installer, sums = selfupdate.find_installer_asset(assets)
    assert installer["name"] == "Slate-Setup-1.7.6.exe"
    assert sums["name"] == "SHA256SUMS.txt"


def test_find_installer_asset_missing_either_returns_none():
    assert selfupdate.find_installer_asset([{"name": "Slate-portable.zip", "download_url": "http://x"}]) == (None, None)


def test_sha256sums_lookup_matches_real_sha256sum_format():
    text = (
        "aaaa11  Slate-portable.zip\n"
        "bbbb22  Slate-Setup-1.7.6.exe\n"
    )
    assert selfupdate._sha256sums_lookup(text, "Slate-Setup-1.7.6.exe") == "bbbb22"


def test_sha256sums_lookup_tolerates_binary_mode_asterisk_prefix():
    assert selfupdate._sha256sums_lookup("cccc33 *Slate-Setup-1.7.6.exe\n", "Slate-Setup-1.7.6.exe") == "cccc33"


def test_sha256sums_lookup_returns_none_when_not_listed():
    assert selfupdate._sha256sums_lookup("aaaa  other-file.exe\n", "Slate-Setup-1.7.6.exe") is None


class _AssetServer(http.server.BaseHTTPRequestHandler):
    FILES = {}  # path -> bytes, set per test

    def do_GET(self):
        body = self.FILES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # quiet test output


@pytest.fixture
def asset_server():
    _AssetServer.FILES = {}
    server = http.server.HTTPServer(("127.0.0.1", 0), _AssetServer)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield port, _AssetServer.FILES
    server.shutdown()


def test_download_and_verify_succeeds_when_hash_matches(asset_server):
    port, files = asset_server
    installer_bytes = b"fake installer contents"
    digest = hashlib.sha256(installer_bytes).hexdigest()
    files["/installer.exe"] = installer_bytes
    files["/SHA256SUMS.txt"] = f"{digest}  Slate-Setup-1.7.6.exe\n".encode("utf-8")

    installer_asset = {"name": "Slate-Setup-1.7.6.exe", "download_url": f"http://127.0.0.1:{port}/installer.exe"}
    sums_asset = {"name": "SHA256SUMS.txt", "download_url": f"http://127.0.0.1:{port}/SHA256SUMS.txt"}

    path, error = selfupdate.download_and_verify(installer_asset, sums_asset, timeout=5)
    assert error is None
    assert path is not None
    with open(path, "rb") as f:
        assert f.read() == installer_bytes


def test_download_and_verify_rejects_tampered_installer(asset_server):
    """Real threat model: a corrupted download or a compromised mirror
    serving the wrong bytes under the right name -- the hash mismatch
    must refuse the file, not just warn."""
    port, files = asset_server
    real_bytes = b"real installer"
    wrong_digest = hashlib.sha256(b"something else entirely").hexdigest()
    files["/installer.exe"] = real_bytes
    files["/SHA256SUMS.txt"] = f"{wrong_digest}  Slate-Setup-1.7.6.exe\n".encode("utf-8")

    installer_asset = {"name": "Slate-Setup-1.7.6.exe", "download_url": f"http://127.0.0.1:{port}/installer.exe"}
    sums_asset = {"name": "SHA256SUMS.txt", "download_url": f"http://127.0.0.1:{port}/SHA256SUMS.txt"}

    path, error = selfupdate.download_and_verify(installer_asset, sums_asset, timeout=5)
    assert path is None
    assert "checksum" in error.lower()


def test_download_and_verify_refuses_when_installer_not_in_manifest(asset_server):
    port, files = asset_server
    files["/installer.exe"] = b"whatever"
    files["/SHA256SUMS.txt"] = b"aaaa  some-other-file.exe\n"

    installer_asset = {"name": "Slate-Setup-1.7.6.exe", "download_url": f"http://127.0.0.1:{port}/installer.exe"}
    sums_asset = {"name": "SHA256SUMS.txt", "download_url": f"http://127.0.0.1:{port}/SHA256SUMS.txt"}

    path, error = selfupdate.download_and_verify(installer_asset, sums_asset, timeout=5)
    assert path is None
    assert "not listed" in error


def test_download_and_verify_fails_soft_on_network_error():
    installer_asset = {"name": "Slate-Setup-1.7.6.exe", "download_url": "http://127.0.0.1:1/nope"}
    sums_asset = {"name": "SHA256SUMS.txt", "download_url": "http://127.0.0.1:1/nope"}

    path, error = selfupdate.download_and_verify(installer_asset, sums_asset, timeout=1)
    assert path is None
    assert error is not None


def test_launch_installer_and_restart_noop_off_windows(monkeypatch):
    """This whole module assumes an Inno Setup .exe -- must never try
    to subprocess anything on a non-Windows platform."""
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    assert selfupdate.launch_installer_and_restart("/fake/installer.exe", "/fake/Slate") is False
