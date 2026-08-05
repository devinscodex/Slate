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

Chrome cascade: menubar_bg = bg (closest to the OS title bar),
tabstrip_bg/toolbar_bg = each family's own authored bg2/bg3 (real,
hand-tuned per-family steps pulled from webUI's own CSS, not a generic
computed lerp -- a family whose identity is "true black, color reserved
for the accent" (bonepaper dark) authors a near-invisible step here on
purpose, which a generic percentage-toward-fg formula can't reproduce).
menubar_fg/toolbar_fg both use the theme's own fg -- readable against
either cascade extreme given a theme's guaranteed bg/fg contrast.
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
    # faint_fg/bg2/bg3/border: real authored values pulled from webUI's
    # own CSS (--text-faint, --bg-2, --bg-3, --line) -- a third, dimmer
    # text tier and real per-family chrome/border steps, not computed.
    "faint_fg", "bg2", "bg3", "border",
)

# The keys _with_chrome_cascade computes from _BASE_KEYS rather than
# storing directly. A built-in theme's color editor can still edit these
# directly (Devin's explicit ask: "full control of the colors of every
# component") -- doing so records a per-theme override (_chrome_overrides
# below) so a later _BASE_KEYS edit re-derives the cascade without
# clobbering it. A custom theme (see is_custom()) has no formula at all;
# every one of its keys, base or cascade, is just a flat stored value.
_CASCADE_KEYS = (
    "menubar_bg", "menubar_fg", "tabstrip_bg", "toolbar_bg", "toolbar_fg",
    "active_tab_bg", "dialog_border",
)
_EDITABLE_KEYS = _BASE_KEYS + _CASCADE_KEYS


def _load_base(family: str, mode: str) -> dict:
    """Loads one family's base palette (_BASE_KEYS) for the given
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


def _with_chrome_cascade(palette: dict, overrides: dict = None) -> dict:
    """menubar_bg=bg (right against the OS title bar). tabstrip_bg/
    toolbar_bg use the family's own authored bg2/bg3 directly -- real
    per-family values (see module docstring), not computed.

    active_tab_bg: 35% of the way from button_bg (the plain tab fill
    every other tab uses) toward the theme's own select_bg -- a tint,
    not a full-saturation fill, using each family's own accent hue.

    dialog_border: Tk's highlightbackground has no real alpha, so this
    approximates a translucent-accent border with a real blend instead:
    fg toward select_bg at 35% (not bg toward select_bg -- a bg-anchored
    blend only cleared ~3:1 contrast in some themes per
    _wcag_contrast_ratio, real risk of reading as near-invisible against
    its own dialog fill; fg-anchored clears 3.7:1+ everywhere). Kept as
    its own computed value, separate from the authored `border` key --
    `border` is a real per-family chrome accent (can read as near-
    invisible against a THEMED dialog's own fill in some families) where
    dialog_border specifically needs guaranteed contrast.

    overrides: optional dict of already-computed _CASCADE_KEYS values
    (from a live per-theme edit, see update_live) applied AFTER the
    formula above -- a real hand-set value always wins over the
    computed default it would otherwise get."""
    palette = dict(palette)
    bg, fg = palette["bg"], palette["fg"]
    palette["menubar_bg"] = bg
    palette["menubar_fg"] = fg
    palette["tabstrip_bg"] = palette["bg2"]
    palette["toolbar_bg"] = palette["bg3"]
    palette["toolbar_fg"] = fg
    palette["active_tab_bg"] = _lerp_toward_fg(palette["button_bg"], palette["select_bg"], 0.35)
    palette["dialog_border"] = _lerp_toward_fg(fg, palette["select_bg"], 0.35)
    if overrides:
        palette.update({k: v for k, v in overrides.items() if k in _CASCADE_KEYS})
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

# Slate Dark: the real published Nord palette (nordtheme.com) --
# Polar Night bg/button_bg/entry_bg (nord0/nord2/nord1), Snow Storm fg
# (nord4), Frost select_bg/highlight_bg (nord8/nord9, two distinct
# blues), muted_fg/border (nord3).
_SLATE_DARK = _load_base("slate", "dark") | {
    # accent2: real Nord Aurora purple (nord15, #B48EAD) -- distinct
    # hue from the Frost blues above, satisfies the no-repeat-colors
    # rule without leaving the real published palette.
    "accent2": "#b48ead",
}
# Slate Light: Flexoki's own real base-300/400/500/600 gray ramp
# (stephango.com/flexoki), landing at nearly the same lightness as the
# original stone tones but genuinely desaturated -- less tan, more
# gray. accent2 shares Dark's real Nord purple for a consistent look
# across the light/dark toggle, same principle the old Solarized
# pairing used.
_SLATE_LIGHT = _load_base("slate", "light") | {
    "accent2": "#b48ead",
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
# border (both modes) = accent2's own value, not a neutral gray -- the
# real WCAG contrast against bg was only 2.24:1 for dark's old neutral
# border, genuinely weak; accent2 gives 7.47:1 dark / 6.76:1 light,
# real green presence instead of gray, same already-vetted color.

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


# THEMES key -> (devs-themes palette family, mode) -- irregular for
# Flexoki specifically (bare "light"/"dark" keys, see THEME_LABELS'
# own comment), so this is a real explicit table, not derived by
# splitting the key string.
_FAMILY_JSON = {
    "slate_light": ("slate", "light"), "slate_dark": ("slate", "dark"),
    "bonepaper_light": ("bonepaper", "light"), "bonepaper_dark": ("bonepaper", "dark"),
    "light": ("flexoki", "light"), "dark": ("flexoki", "dark"),
    "martin_light": ("martin", "light"), "martin_dark": ("martin", "dark"),
}

# devs-themes is Slate's sibling checkout (see pull_themes.sh's own
# comment for the same assumption) -- the real source of truth every
# consumer (Slate, webUI, Runestone) pulls from.
_DEVS_THEMES_PALETTES = Path(__file__).parent.parent / "devs-themes" / "palettes"


def family_and_mode(theme_name: str) -> tuple:
    """(family, mode) for a THEMES key, e.g. "martin_dark" ->
    ("martin", "dark") -- for locating that theme's real source JSON.
    Raises KeyError for an unrecognized name rather than guessing."""
    return _FAMILY_JSON[theme_name]


def is_custom(theme_name: str) -> bool:
    """True for a user-created theme (save_as_new_theme). Every built-in
    theme has a real devs-themes family/mode mapping in _FAMILY_JSON; a
    custom theme doesn't -- its full palette is a standalone saved
    snapshot, never re-derived from a base+cascade formula."""
    return theme_name not in _FAMILY_JSON


# Per-built-in-theme overrides of _CASCADE_KEYS values (a live edit to a
# normally-computed key like menubar_bg). Session state, restored at
# startup by load_saved_chrome_overrides() and persisted by
# save_family_values(); never touched for a custom theme (is_custom()),
# which has no formula to protect an override from in the first place.
_chrome_overrides: dict = {}


def update_live(theme_name: str, key: str, hexval: str):
    """Mutates THEMES[theme_name] in place and, for a built-in theme,
    recomputes every OTHER chrome-cascade-derived key from it -- a live
    color editor calls this then triggers a normal repaint, same as any
    other theme change. No special-cased 'preview' palette: the running
    app's real THEMES dict just changes under it.

    key may be any of _EDITABLE_KEYS (_BASE_KEYS or _CASCADE_KEYS) for a
    built-in theme -- editing a _BASE_KEYS value re-derives the cascade
    (preserving any earlier _CASCADE_KEYS overrides on this same theme);
    editing a _CASCADE_KEYS value directly records it as an override so
    a later _BASE_KEYS edit won't silently overwrite it again. A custom
    theme has no formula at all -- every key is just a flat stored value,
    key may be anything already present in its palette."""
    if is_custom(theme_name):
        if key not in THEMES[theme_name]:
            raise ValueError(f"{key!r} is not a key in this theme's palette")
        THEMES[theme_name] = dict(THEMES[theme_name]) | {key: hexval}
        return
    if key not in _EDITABLE_KEYS:
        raise ValueError(f"{key!r} is not an editable key")
    if key in _CASCADE_KEYS:
        _chrome_overrides.setdefault(theme_name, {})[key] = hexval
    palette = dict(THEMES[theme_name])
    palette[key] = hexval
    if key in _BASE_KEYS:
        THEMES[theme_name] = _with_chrome_cascade(palette, _chrome_overrides.get(theme_name))
    else:
        THEMES[theme_name] = palette


def save_family_values(theme_name: str) -> Path:
    """Writes THEMES[theme_name]'s current _BASE_KEYS values, plus any
    live _CASCADE_KEYS overrides (_chrome_overrides), back into
    devs-themes/palettes/<family>.json's <mode> section AND Slate's own
    theme_data/<family>.json pulled copy, so both stay in sync the
    instant you save (no separate pull_themes.sh run needed). Overrides
    are stored under a "slate_chrome_overrides" sub-key -- an extra,
    Slate-only key devs-themes' shared schema already tolerates (see
    bonepaper.json's own external_link, same convention). Keeps every
    other key in either file untouched. Returns the devs-themes path
    written, for the caller to report."""
    family, mode = family_and_mode(theme_name)
    live = THEMES[theme_name]
    values = {k: live[k] for k in _BASE_KEYS}
    overrides = _chrome_overrides.get(theme_name, {})

    def _write(path):
        data = json.loads(path.read_text())
        mode_data = data.setdefault(mode, {})
        mode_data.update(values)
        if overrides:
            mode_data["slate_chrome_overrides"] = overrides
        else:
            mode_data.pop("slate_chrome_overrides", None)
        path.write_text(json.dumps(data, indent=2) + "\n")

    devs_path = _DEVS_THEMES_PALETTES / f"{family}.json"
    _write(devs_path)
    _write(_THEME_DATA_DIR / f"{family}.json")
    return devs_path


def _load_chrome_overrides(family: str, mode: str) -> dict:
    data = json.loads((_THEME_DATA_DIR / f"{family}.json").read_text())
    return data.get(mode, {}).get("slate_chrome_overrides", {})


def reload_from_disk(theme_name: str):
    """Discards live in-memory edits for one theme (both _BASE_KEYS AND
    any _CASCADE_KEYS overrides), reloading its real last-saved-or-
    pulled state straight from Slate's own theme_data/<family>.json --
    the color editor's "Reset" action."""
    family, mode = family_and_mode(theme_name)
    base = _load_base(family, mode)
    accent2 = THEMES[theme_name].get("accent2")
    palette = base if accent2 is None else base | {"accent2": accent2}
    overrides = _load_chrome_overrides(family, mode)
    if overrides:
        _chrome_overrides[theme_name] = overrides
    else:
        _chrome_overrides.pop(theme_name, None)
    THEMES[theme_name] = _with_chrome_cascade(palette, overrides)


def load_saved_chrome_overrides():
    """Call once at app startup (not at import -- keeps `import theme`
    side-effect-free for tests). Restores every built-in theme's
    previously-saved _CASCADE_KEYS overrides, if any, so a hand-tuned
    menubar/toolbar/etc color survives a relaunch, not just the session
    that set it."""
    for name in _FAMILY_JSON:
        reload_from_disk(name)


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


# --- custom (user-created) themes -------------------------------------
# A custom theme is a standalone flat-palette snapshot -- no family/mode,
# no formula, no _FAMILY_JSON entry (that absence IS is_custom()'s test).
# Stored as its own file rather than folded into devs-themes: it's a
# personal Slate-only theme, not a shared cross-app palette.
CUSTOM_THEMES_FILE = CONFIG_DIR / "custom_themes.json"


def load_custom_themes():
    """Call once at app startup (not at import -- keeps `import theme`
    side-effect-free for tests). Populates THEMES/THEME_LABELS with any
    themes previously saved via save_as_new_theme, so they show up in
    the Settings theme picker exactly like a built-in family."""
    if not CUSTOM_THEMES_FILE.exists():
        return
    try:
        data = json.loads(CUSTOM_THEMES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return
    for key, entry in data.items():
        THEMES[key] = entry["palette"]
        THEME_LABELS[entry["label"]] = key


def _slugify(text: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in text.strip().lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "custom"


def _write_custom_themes():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    label_by_key = {v: k for k, v in THEME_LABELS.items()}
    data = {
        key: {"label": label_by_key[key], "palette": THEMES[key]}
        for key in THEMES if is_custom(key)
    }
    CUSTOM_THEMES_FILE.write_text(json.dumps(data, indent=2) + "\n")


def save_as_new_theme(source_theme_name: str, display_name: str) -> str:
    """Snapshots THEMES[source_theme_name]'s current full live palette
    (base + cascade + any overrides + accent2) under a brand-new theme
    key/label derived from display_name -- the source theme itself is
    untouched, edited in place or not. Mode suffix ("Light"/"Dark") is
    added automatically from the source palette's own is_dark, matching
    THEME_LABELS' existing "<Family> Light"/"<Family> Dark" convention
    (see slate.py's Settings dialog, which groups by that exact suffix)
    so the new theme's single mode slots into the picker the same way
    any other single-mode family would. Returns the new internal key.
    Raises ValueError if display_name is empty or already taken."""
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("Name can't be empty.")
    mode = "dark" if THEMES[source_theme_name]["is_dark"] else "light"
    label = f"{display_name} {mode.title()}"
    if label in THEME_LABELS:
        raise ValueError(f'"{label}" already exists -- pick a different name.')
    base_key = _slugify(display_name)
    key = f"{base_key}_{mode}"
    suffix = 2
    while key in THEMES:
        key = f"{base_key}{suffix}_{mode}"
        suffix += 1
    THEMES[key] = dict(THEMES[source_theme_name])
    THEME_LABELS[label] = key
    _write_custom_themes()
    return key


def save_custom_theme(theme_name: str):
    """Re-saves an already-custom theme's current live (edited) palette
    back to disk in place -- the color editor's Save action when the
    theme being edited is itself a custom one, not a built-in family."""
    if not is_custom(theme_name):
        raise ValueError(f'"{theme_name}" is a built-in theme, not custom.')
    _write_custom_themes()


def reload_custom_theme(theme_name: str):
    """Discards live in-memory edits for a custom theme, reloading its
    last-saved palette from CUSTOM_THEMES_FILE -- the color editor's
    "Reset" action, custom-theme counterpart to reload_from_disk."""
    if not CUSTOM_THEMES_FILE.exists():
        raise KeyError(theme_name)
    data = json.loads(CUSTOM_THEMES_FILE.read_text())
    if theme_name not in data:
        raise KeyError(theme_name)
    THEMES[theme_name] = data[theme_name]["palette"]
