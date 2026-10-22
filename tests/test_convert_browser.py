"""_find_browser's candidate list and fallback order -- pure path/PATH
logic, no real browser or subprocess needed to test it."""
import convert


def _only_exists(*wanted_paths):
    """monkeypatch target: os.path.exists is True only for these exact
    paths (everything else -- including WSL-mount variants -- False)."""
    wanted = set(wanted_paths)
    return lambda p: p in wanted


def test_finds_brave_first_when_present(monkeypatch):
    brave = convert._BROWSER_CANDIDATES[0]
    monkeypatch.setattr(convert.os.path, "exists", _only_exists(brave))
    assert convert._find_browser() == brave


def test_finds_edge_when_only_edge_installed(monkeypatch):
    """Real incident: MEG's standard Windows image ships Edge only, no
    Chrome/Brave -- html_to_pdf raised FileNotFoundError on a real
    artifacts-folder .html file because Edge wasn't in the candidate
    list at all."""
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    assert edge in convert._BROWSER_CANDIDATES
    monkeypatch.setattr(convert.os.path, "exists", _only_exists(edge))
    assert convert._find_browser() == edge


def test_falls_back_to_path_for_edge(monkeypatch):
    monkeypatch.setattr(convert.os.path, "exists", _only_exists())
    monkeypatch.setattr(
        convert.shutil, "which",
        lambda name: r"C:\custom\msedge.exe" if name == "msedge.exe" else None,
    )
    assert convert._find_browser() == r"C:\custom\msedge.exe"


def test_raises_with_edge_mentioned_when_nothing_found(monkeypatch):
    monkeypatch.setattr(convert.os.path, "exists", _only_exists())
    monkeypatch.setattr(convert.shutil, "which", lambda name: None)
    try:
        convert._find_browser()
        assert False, "expected FileNotFoundError"
    except FileNotFoundError as e:
        assert "Edge" in str(e)
