"""Light/dark color palettes for Slate's UI. Pure data + a pure lookup
function -- no Tkinter imports here on purpose, so this stays trivially
testable without a display. slate.py owns actually walking the widget
tree and applying these colors (recursive tk widget config + a ttk.Style
pass for Notebook/Treeview).

Real, verified platform constraint, not assumed: on Windows, tk.Menu's
dropdown popups are drawn by the native Win32 menu renderer, which
does NOT respect Tk's bg/fg/activebackground options the way X11 does
-- confirmed via Tkinter's own documented platform behavior. Setting
these colors here is harmless (Windows just ignores them) and correct
on Linux/X11 (this dev environment), but the actual File/Edit/View
dropdown appearance on a real Windows deployment will follow Windows'
own light/dark OS theme, not this toggle. Everything else (toolbar,
canvas, home screen, dialogs, tabs, TOC) is drawn by Tk itself and
themes correctly on every platform.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
PREF_FILE = CONFIG_DIR / "theme.json"

LIGHT = {
    # Real bug caught live: "SystemButtonFace" is a Windows-only Tk
    # symbolic color name -- crashes with "unknown color name" on
    # Linux/X11 Tk (confirmed directly, not assumed). "#d9d9d9" is
    # Tk's own actual compiled-in default widget gray, portable
    # everywhere.
    "bg": "#d9d9d9",
    "fg": "black",
    "button_bg": "#d9d9d9",
    "entry_bg": "white",
    "canvas_bg": "gray80",
    "select_bg": "#cce4ff",
    "muted_fg": "gray40",
}

DARK = {
    "bg": "#2b2b2b",
    "fg": "#e8e8e8",
    "button_bg": "#3c3c3c",
    "entry_bg": "#1e1e1e",
    "canvas_bg": "#1a1a1a",
    "select_bg": "#3a5a7a",
    "muted_fg": "#9a9a9a",
}


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def load_preference() -> bool:
    """Persisted across launches (~/.slate/theme.json, same convention
    as recent.py/gate.py) -- without this, every launch starts light
    and then visibly flashes to dark the moment the app applies a
    saved preference, which is exactly the jarring effect this exists
    to avoid. Missing/corrupt file -> light, not an error."""
    if not PREF_FILE.exists():
        return False
    try:
        return json.loads(PREF_FILE.read_text()).get("dark", False)
    except (json.JSONDecodeError, OSError):
        return False


def save_preference(dark: bool):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PREF_FILE.write_text(json.dumps({"dark": dark}))
