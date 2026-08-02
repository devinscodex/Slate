"""User preferences persisted across launches (~/.slate/settings.json),
same convention as recent.py/theme.py (plain JSON, stdlib only,
defensive load). Kept separate from theme.py's own theme.json -- theme
selection stays there unchanged; this covers everything else: zoom,
continuous scroll, side by side, colorize_pages, TTS voice/speed,
toc_visible.

zoom defaults to None (meaning "use Viewer.DEFAULT_ZOOM," no user
override yet) rather than a number -- distinguishes "never set" from
"explicitly set to some previously-chosen value," so a user who's never
touched zoom still gets the designed default, not an arbitrary 1.0.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "zoom": None,
    "continuous_scroll": True,
    "side_by_side": False,
    "colorize_pages": False,
    "crop_to_content": False,
    "toc_visible": True,
    # Integer POINT delta from whatever size Tk picked as the platform's
    # native default at first launch (theme.py._UI_FONT_BASE_SIZES,
    # captured once) -- not an absolute point size or raw pixel count,
    # so the same delta reads as a proportionally similar bump regardless
    # of the native baseline. Default 0 = unchanged from the OS default.
    "ui_font_scale": 0,
    "tts_voice": "northern_english_male",
    "tts_speed": 1.0,
    # Which documents were open, each as {"path": ..., "page": N}, plus
    # window size/position -- relaunch restores the exact prior state.
    "open_tabs": [],
    "window_geometry": None,  # Tk geometry string "WxH+X+Y", or None = center-on-screen (first run)
}


def load() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(changes: dict):
    """Merge-and-write, not overwrite -- callers pass only the key(s)
    that just changed (e.g. save({"zoom": 2.0})) without needing to know
    or re-supply every other current value."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current = load()
    current.update({k: v for k, v in changes.items() if k in DEFAULTS})
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))
