"""Named color themes for Slate's UI. Pure data + pure lookup functions
-- no Tkinter imports here, so this stays trivially testable without a
display. slate.py owns actually walking the widget tree and applying
these colors (recursive tk widget config + a ttk.Style pass for
Notebook/Treeview) and inverting the rendered page image for "is_dark"
themes.

Platform constraint: on Windows, tk.Menu's dropdown popups are drawn by
the native Win32 menu renderer, which does NOT respect Tk's
bg/fg/activebackground options the way X11 does. Setting these colors
is harmless (Windows ignores them) and correct on Linux/X11, but the
actual File/Edit/View dropdown appearance on Windows follows the OS
theme, not this picker. Everything else (toolbar, canvas, home screen,
dialogs, tabs, TOC) is drawn by Tk itself and themes correctly on every
platform.

Roster: 4 families (Slate/Bonepaper/Flexoki/Martin), light+dark each,
8 variants total.

Chrome cascade: one consistent rule across every variant, not a
per-theme special case -- menubar_bg = bg (closest to the OS title
bar), toolbar_bg = 16% toward fg (closest to the content/card level),
tabstrip_bg = 8% toward fg (the midpoint step), a real 3-step visual
gradient top to bottom. menubar_fg/toolbar_fg both use the theme's own
fg -- readable against either cascade extreme given a theme's
guaranteed bg/fg contrast.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
PREF_FILE = CONFIG_DIR / "theme.json"

# theme_data/*.json are pulled copies of devs-themes/palettes/*.json
# (https://github.com/devinscodex/devs-themes, the central source of
# truth) -- run pull_themes.sh to refresh. Copy, not symlink, on
# purpose: Slate is free to tweak its own copy independently without
# touching the shared repo.
_THEME_DATA_DIR = Path(__file__).parent / "theme_data"


_BASE_KEYS = (
    "bg", "fg", "button_bg", "entry_bg", "canvas_bg",
    "select_bg", "muted_fg", "highlight_bg",
)


def _load_base(family: str, mode: str) -> dict:
    """Loads one family's base 8-key palette (_BASE_KEYS) for the given
    mode ("light" or "dark") from theme_data/<family>.json, plus is_dark
    (not stored in the JSON itself, derived from which mode was asked
    for). Whitelisted to _BASE_KEYS on purpose: devs-themes is a shared
    repo across apps and can carry extra per-consumer keys (e.g.
    bonepaper.json's external_link, Runestone-only) that aren't part of
    Slate's own palette shape."""
    data = json.loads((_THEME_DATA_DIR / f"{family}.json").read_text())[mode]
    return {k: data[k] for k in _BASE_KEYS} | {"is_dark": mode == "dark"}

DEFAULT_THEME = "slate_light"


def _hex_to_rgb(hexval: str):
    return tuple(int(hexval[i:i + 2], 16) for i in (1, 3, 5))


def _rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in rgb)


def _midpoint(hex_a: str, hex_b: str) -> str:
    """Exact RGB midpoint between two hex colors."""
    a, b = _hex_to_rgb(hex_a), _hex_to_rgb(hex_b)
    return _rgb_to_hex(tuple((x + y) // 2 for x, y in zip(a, b)))


def _lerp_toward_fg(bg: str, fg: str, fraction: float) -> str:
    """Interpolates a fixed FRACTION of the way from bg toward fg.
    Anchoring a cascade step to button_bg can produce mathematically-
    distinct but visually identical steps when bg and button_bg are
    both very close to black (or white). Interpolating toward fg
    instead guarantees a real, always-visible step, since bg/fg
    contrast is guaranteed high by definition of a working theme."""
    a, b = _hex_to_rgb(bg), _hex_to_rgb(fg)
    return _rgb_to_hex(tuple(round(x + fraction * (y - x)) for x, y in zip(a, b)))


def _with_chrome_cascade(palette: dict) -> dict:
    """menubar_bg=bg (0% toward fg, right against the OS title bar),
    tabstrip_bg=8% toward fg, toolbar_bg=16% toward fg (closest to the
    content/card level) -- one consistent, self-computing rule for
    every family, riding the theme's own guaranteed bg<->fg contrast
    rather than button_bg (which keeps its own original role: tab
    fills, general Button widgets).

    active_tab_bg: 35% of the way from button_bg (the plain tab fill
    every other tab uses) toward the theme's own select_bg -- a tint,
    not a full-saturation fill, using each family's own accent hue.

    dialog_border: Tk's highlightbackground has no real alpha, so this
    approximates a translucent-accent border with a real blend instead:
    fg toward select_bg at 35% (not bg toward select_bg -- a bg-anchored
    blend only cleared ~3:1 contrast in some themes per
    _wcag_contrast_ratio, real risk of reading as near-invisible against
    its own dialog fill; fg-anchored clears 3.7:1+ everywhere)."""
    palette = dict(palette)
    bg, fg = palette["bg"], palette["fg"]
    palette["menubar_bg"] = bg
    palette["menubar_fg"] = fg
    palette["tabstrip_bg"] = _lerp_toward_fg(bg, fg, 0.08)
    palette["toolbar_bg"] = _lerp_toward_fg(bg, fg, 0.16)
    palette["toolbar_fg"] = fg
    palette["active_tab_bg"] = _lerp_toward_fg(palette["button_bg"], palette["select_bg"], 0.35)
    palette["dialog_border"] = _lerp_toward_fg(fg, palette["select_bg"], 0.35)
    return palette


# Flexoki: real published values, stephango.com/flexoki. bg/button_bg
# are base-950 #1C1B1A / base-900 #282726; entry_bg (#100f0f) is
# Flexoki's own "black" tier. select_bg/highlight_bg are Flexoki's real
# blue-400 #4385BE.
_STANDARD_DARK = _load_base("flexoki", "dark") | {
    # accent2: real Flexoki purple (--color-purple under .theme-dark).
    # Flexoki's own orange was tried first but trips
    # test_no_dark_theme_has_brown_tones (no brown/tan/rust hues allowed
    # in any dark theme -- orange/red/yellow are all warm R>G>B hues
    # that trigger it).
    "accent2": "#8b7ec8",
}
# select_bg/highlight_bg: real Flexoki blue-600 #205EA6.
_STANDARD_LIGHT = _load_base("flexoki", "light") | {
    # Real Flexoki purple-600 (--color-purple under .theme-light) --
    # same hue family as Dark's accent2 so the "second accent" stays
    # recognizable across a light/dark toggle.
    "accent2": "#5e409d",
}

# Slate: dark built on official Solarized neutrals (bg/button_bg/
# muted_fg/fg, ethanschoonover.com/solarized) with the accent replaced
# by a desaturated true moss (h:95 s:40% l:44% -> #699d43).
_SLATE_DARK = _load_base("slate", "dark") | {
    # accent2: real Solarized magenta (#d33682) -- same spec Slate's own
    # primary neutrals come from. Solarized's real orange was tried
    # first but trips test_no_dark_theme_has_brown_tones. Solarized's
    # accent hues are identical across light and dark by the spec's own
    # design, so light/dark share this value.
    "accent2": "#d33682",
}
_SLATE_LIGHT = _load_base("slate", "light") | {
    "accent2": "#d33682",  # same real Solarized magenta as Dark above
}

# Bonepaper: light = Boneink's real light half (bone-paper, fixed
# teal-jade accent ~158deg). Dark = real sampled night-rain values
# (numpy over 5 reference photos, not picked by eye).
_BONEPAPER_DARK = _load_base("bonepaper", "dark") | {
    # accent2: bonepaper.json's own external_link value (#9d8cf0),
    # Runestone's real hyperlink color for this family -- a genuine
    # lavender/violet. Runestone's own H3-header/code-keyword coral
    # (#d98f7a) was tried first but trips
    # test_no_dark_theme_has_brown_tones.
    "accent2": "#9d8cf0",
}
_BONEPAPER_LIGHT = _load_base("bonepaper", "light") | {
    "accent2": "#5b3fa6",  # bonepaper.json's own external_link, light mode
}

# Martin: real Martin Energy Group brand colors, from
# presentation/meg-theme.css (pulled from martinenergygroup.com's live
# Elementor global palette) -- not derived from the brand PDF's Pantone
# CMYK values (naive CMYK->RGB on saturated greens oversaturates).
# select_bg is the bright primary #62A945 (checked-toggle fill);
# highlight_bg is the secondary "Dark Green" #4A7637 (text selection/
# TOC highlight) -- both real, verified MEG brand greens, not invented.
_MARTIN_LIGHT = _load_base("martin", "light") | {
    # accent2: martin.css's own light-mode link-color-hover (#3d5f2c) --
    # a genuinely different shade of the same green (Martin is
    # deliberately single-hue-family by brand), not equal to select_bg
    # or highlight_bg.
    "accent2": "#3d5f2c",
}
_MARTIN_DARK = _load_base("martin", "dark") | {
    "accent2": "#7cc25a",  # martin.css's own dark-mode link-color-hover
}

THEMES = {
    "light": _with_chrome_cascade(_STANDARD_LIGHT),
    "dark": _with_chrome_cascade(_STANDARD_DARK),
    "slate_light": _with_chrome_cascade(_SLATE_LIGHT),
    "slate_dark": _with_chrome_cascade(_SLATE_DARK),
    "bonepaper_light": _with_chrome_cascade(_BONEPAPER_LIGHT),
    "bonepaper_dark": _with_chrome_cascade(_BONEPAPER_DARK),
    "martin_light": _with_chrome_cascade(_MARTIN_LIGHT),
    "martin_dark": _with_chrome_cascade(_MARTIN_DARK),
}

# Display label -> internal THEMES key. Slate is always top/default;
# the other three sort alphabetically (Bonepaper, Flexoki, Martin).
THEME_LABELS = {
    "Slate Light": "slate_light",
    "Slate Dark": "slate_dark",
    "Bonepaper Light": "bonepaper_light",
    "Bonepaper Dark": "bonepaper_dark",
    # Values are Steph Ango's real published Flexoki palette
    # (stephango.com/flexoki); display label matches the palette's own
    # project name.
    "Flexoki Light": "light",
    "Flexoki Dark": "dark",
    # Real Martin Energy Group brand colors -- see _MARTIN_LIGHT/
    # _MARTIN_DARK's own comment for sourcing.
    "Martin Light": "martin_light",
    "Martin Dark": "martin_dark",
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
