"""User preferences persisted across launches (~/.slate/settings.json),
same convention as recent.py/theme.py (plain JSON, stdlib only, defensive
load). Kept as its OWN file rather than folded into theme.py's
theme.json -- theme.py predates this, already has its own working
load_preference()/save_preference() pair and tests, and theme selection
stays there unchanged; this covers everything else Devin asked to
persist (2026-07-26 handoff): zoom level, continuous scroll, side by
side, colorize_pages, TTS voice + speed. toc_visible (whether the
outline panel was open) added too -- Devin: "any other settings you
think would fit Slate," and remembering panel state across launches is
the same class of "don't reset to a jarring default" fix as everything
else here.

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
    # UI font scale (Devin, 2026-07-29: "the font needs to be adjustable
    # for the UI, not just the page... pretty small rn"). An integer
    # POINT delta from whatever size Tk itself picked as the platform's
    # own native default at first launch (theme.py._UI_FONT_BASE_SIZES,
    # captured once, never hardcoded) -- not an absolute point size and
    # not a raw pixel count, so the SAME delta reads as a proportionally
    # similar bump whether Tk's native baseline happens to be small
    # (common Linux X11 default) or already larger (Windows/HiDPI often
    # picks a bigger native default on its own). Default 0 = exactly
    # whatever Tk/the OS would have shown anyway, unchanged from every
    # earlier release.
    "ui_font_scale": 0,
    "tts_voice": "northern_english_male",
    "tts_speed": 1.0,
    # Session restore (Devin, 2026-07-26: "keep documents open across
    # sessions too like VSCodium/Sumatra"; extended same day to include
    # page position: "i want my Slate session to be restored (document
    # position)") -- which documents were open, each as {"path": ...,
    # "page": N}, plus the main window's size/position, so relaunching
    # Slate lands back exactly where it left off, not just at the right
    # file with a blank first page.
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
