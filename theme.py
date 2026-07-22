"""Named color themes for Slate's UI. Pure data + pure lookup functions
-- no Tkinter imports here on purpose, so this stays trivially testable
without a display. slate.py owns actually walking the widget tree and
applying these colors (recursive tk widget config + a ttk.Style pass
for Notebook/Treeview) and inverting the rendered page image for
"is_dark" themes.

Real, verified platform constraint, not assumed: on Windows, tk.Menu's
dropdown popups are drawn by the native Win32 menu renderer, which
does NOT respect Tk's bg/fg/activebackground options the way X11 does
-- confirmed via Tkinter's own documented platform behavior. Setting
these colors here is harmless (Windows just ignores them) and correct
on Linux/X11 (this dev environment), but the actual File/Edit/View
dropdown appearance on a real Windows deployment will follow Windows'
own light/dark OS theme, not this picker. Everything else (toolbar,
canvas, home screen, dialogs, tabs, TOC) is drawn by Tk itself and
themes correctly on every platform.

Palette sources, verified live (not from memory) before writing these,
Devin's ask: Solarized -- ethanschoonover.com/solarized (official base
tones/blue accent); Gruvbox -- the project's own colors/gruvbox.vim
source; Flexoki -- stephango.com/flexoki (Steph Ango's own published
hex values). Mosscairn ("our custom Runestone CSS theme") -- Devin's
own hand-built Obsidian snippet, read directly from
runestone/.obsidian/snippets/mosscairn.css: light is "faded parchment"
(--color-base-00 #a39a84 page, moss-green rgb(88,118,58) accent), dark
is "watchtower night" (--color-base-00 #00242e deep teal page,
lamplight-moss rgb(163,183,42) accent). That file only overrides
Obsidian's raw --color-base-* palette + accent/link colors inside its
.theme-dark block, not the semantic --background-* variables (those
inherit Obsidian's own dark-theme defaults there) -- so the dark
mapping below reads color-base-00/05/10/20/50/100 directly as the
nearest equivalent to Slate's own bg/entry_bg/button_bg/muted_fg/fg
roles, the same relative-position pattern the light block spells out
explicitly.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
PREF_FILE = CONFIG_DIR / "theme.json"

DEFAULT_THEME = "mosscairn_dark"

THEMES = {
    "light": {
        # "SystemButtonFace" (Windows-only Tk symbolic name) crashed
        # with "unknown color name" on Linux/X11 Tk, confirmed live --
        # "#d9d9d9" is Tk's own actual compiled-in default widget gray,
        # portable everywhere.
        "bg": "#d9d9d9", "fg": "black", "button_bg": "#d9d9d9",
        # "gray80" (Tk-style name) isn't recognized by PIL's ImageColor
        # (confirmed live) -- render() recolors the page via
        # ImageOps.colorize using these same values, so every color
        # here needs to work in both Tk and PIL. "#cccccc" is gray80's
        # own real RGB value (204,204,204), portable everywhere.
        "entry_bg": "white", "canvas_bg": "#cccccc",
        "select_bg": "#cce4ff", "muted_fg": "gray40", "is_dark": False,
    },
    "dark": {
        "bg": "#2b2b2b", "fg": "#e8e8e8", "button_bg": "#3c3c3c",
        "entry_bg": "#1e1e1e", "canvas_bg": "#1a1a1a",
        "select_bg": "#3a5a7a", "muted_fg": "#9a9a9a", "is_dark": True,
    },
    "solarized_dark": {
        "bg": "#002b36", "fg": "#839496", "button_bg": "#073642",
        "entry_bg": "#073642", "canvas_bg": "#002b36",
        "select_bg": "#268bd2", "muted_fg": "#586e75", "is_dark": True,
    },
    "solarized_light": {
        "bg": "#fdf6e3", "fg": "#657b83", "button_bg": "#eee8d5",
        "entry_bg": "#fdf6e3", "canvas_bg": "#fdf6e3",
        "select_bg": "#268bd2", "muted_fg": "#93a1a1", "is_dark": False,
    },
    "gruvbox_dark": {
        "bg": "#282828", "fg": "#ebdbb2", "button_bg": "#3c3836",
        "entry_bg": "#1d2021", "canvas_bg": "#282828",
        "select_bg": "#83a598", "muted_fg": "#928374", "is_dark": True,
    },
    "gruvbox_light": {
        "bg": "#fbf1c7", "fg": "#3c3836", "button_bg": "#ebdbb2",
        "entry_bg": "#fbf1c7", "canvas_bg": "#fbf1c7",
        "select_bg": "#83a598", "muted_fg": "#928374", "is_dark": False,
    },
    "flexoki_dark": {
        "bg": "#1c1b1a", "fg": "#e6e4d9", "button_bg": "#282726",
        "entry_bg": "#100f0f", "canvas_bg": "#1c1b1a",
        "select_bg": "#205ea6", "muted_fg": "#6f6e69", "is_dark": True,
    },
    "flexoki_light": {
        "bg": "#fffcf0", "fg": "#100f0f", "button_bg": "#f2f0e5",
        "entry_bg": "#fffcf0", "canvas_bg": "#fffcf0",
        "select_bg": "#205ea6", "muted_fg": "#b7b5ac", "is_dark": False,
    },
    "mosscairn_dark": {
        "bg": "#05313d", "fg": "#e8e4d0", "button_bg": "#093947",
        "entry_bg": "#022a35", "canvas_bg": "#00242e",
        "select_bg": "#a3b72a", "muted_fg": "#657b83", "is_dark": True,
    },
    "mosscairn_light": {
        "bg": "#948b78", "fg": "#1c1a16", "button_bg": "#8a816f",
        "entry_bg": "#8f8674", "canvas_bg": "#a39a84",
        "select_bg": "#58763a", "muted_fg": "#433f39", "is_dark": False,
    },
}

# Display label -> internal THEMES key, in menu order.
THEME_LABELS = {
    "Light": "light",
    "Dark": "dark",
    "Solarized Dark": "solarized_dark",
    "Solarized Light": "solarized_light",
    "Gruvbox Dark": "gruvbox_dark",
    "Gruvbox Light": "gruvbox_light",
    "Flexoki Dark": "flexoki_dark",
    "Flexoki Light": "flexoki_light",
    "Mosscairn Dark": "mosscairn_dark",
    "Mosscairn Light": "mosscairn_light",
}

# Kept as plain names too (not just THEMES["light"]/["dark"]) -- several
# tests already reference these directly, and it's a reasonable stable
# alias for the two built-in defaults either way.
LIGHT = THEMES["light"]
DARK = THEMES["dark"]


def get_palette(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def load_preference() -> str:
    """Persisted across launches (~/.slate/theme.json, same convention
    as recent.py/gate.py) -- without this, every launch starts on the
    default theme and visibly flashes to the saved one a moment later,
    which is exactly the jarring effect this exists to avoid. Missing/
    corrupt/unrecognized-theme-name file -> the default, not an error."""
    if not PREF_FILE.exists():
        return DEFAULT_THEME
    try:
        name = json.loads(PREF_FILE.read_text()).get("theme", DEFAULT_THEME)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_THEME
    return name if name in THEMES else DEFAULT_THEME


def save_preference(name: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PREF_FILE.write_text(json.dumps({"theme": name}))
