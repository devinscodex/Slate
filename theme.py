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

Roster history (Devin, 2026-07-25): "make standard light/dark
modes the same as Flexoki, and get rid of Flexoki as a separate
option, also delete Gruvbox themes... main will be Dark/Light,
Solarized Light/Dark, Inkbone Light/Dark." Down from 5 families (10
variants) to 3 families (6 variants) at the time -- "light"/"dark" now
carry Flexoki's real published values directly (stephango.com/flexoki,
verified live). Both Solarized and Inkbone later retired (2026-07-29,
see THEME_LABELS' own comment) once Mosscairn/Boneink existed and
covered the same ground. Boneink itself was then folded into Inkrain
(see THEME_LABELS again). Same day, both surviving custom families were
renamed once more per Devin's direct ask: Mosscairn -> Slate ("or just
Slate" -- this is the app's own Solarized-derived house theme, "Slate
dark = solarized dark basically (desaturaized)"), Inkrain -> Bonepaper
("i prefer bonepaper..."). Current roster is Standard/Bonepaper/Slate.

Chrome cascade (Devin, 2026-07-25, same request): "make menu bar
cascade down in color from window bar down to tabs, to toolbar making
it aesthetic," applied to all 3 core families. One consistent rule
across all 6 variants, not a per-theme special case: menubar_bg = bg
(the extreme closest to the OS title bar), toolbar_bg = button_bg (the
extreme closest to the content/card level), tabstrip_bg = the exact
RGB midpoint between them -- a real 3-step visual gradient from top to
bottom, not three arbitrary picks. Scrollbars share toolbar_bg/fg
(same visual "closest to content" band, no 4th tone). menubar_fg/
toolbar_fg both use the theme's own fg -- readable against either
cascade extreme in every family tested here (all have real contrast
margin between fg and both bg/button_bg).
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
PREF_FILE = CONFIG_DIR / "theme.json"

# Inkbone retired 2026-07-29 ("let's get rid of inkbone") -- Boneink
# already shared its exact bg/fg bones (same "heavy black night noir"
# look inkbone_dark was originally picked as default for), so nothing
# in that visual identity is actually lost. Default went through
# slate_dark (named "mosscairn_dark" at the time, "these colors are
# looking GREAT") before Devin's final call, same day: slate_light --
# "starting/defaulting to Slate light, that stone look."
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
    Real fix (Devin, 2026-07-25, live screenshot review: "menubar
    doesn't cascade in hue/darkness") for a real perceptual bug in the
    first cascade formula: anchoring toolbar_bg to button_bg produced
    mathematically-distinct but VISUALLY IDENTICAL steps for
    inkbone_dark specifically (bg=#0e0c0a, button_bg=#1c1815 -- both so
    close to pure black the human eye can't tell them apart, even
    though the hex values genuinely differ). Interpolating toward fg
    instead guarantees a REAL, always-visible step, because bg/fg
    contrast is guaranteed high by definition of a working theme (that
    contrast is what makes body text readable) -- the cascade rides
    that same guaranteed contrast instead of depending on how far apart
    bg and button_bg happen to be in each theme."""
    a, b = _hex_to_rgb(bg), _hex_to_rgb(fg)
    return _rgb_to_hex(tuple(round(x + fraction * (y - x)) for x, y in zip(a, b)))


def _with_chrome_cascade(palette: dict) -> dict:
    """menubar_bg=bg (0% toward fg, right against the OS title bar),
    tabstrip_bg=8% toward fg, toolbar_bg=16% toward fg (closest to the
    content/card level) -- one consistent, self-computing rule for
    every "core" family (Standard/Inkbone/Solarized), riding the
    theme's own guaranteed bg<->fg contrast rather than button_bg
    (which button_bg keeps for its own original role: tab fills,
    general Button widgets -- unaffected by this cascade now)."""
    palette = dict(palette)
    bg, fg = palette["bg"], palette["fg"]
    palette["menubar_bg"] = bg
    palette["menubar_fg"] = fg
    palette["tabstrip_bg"] = _lerp_toward_fg(bg, fg, 0.08)
    palette["toolbar_bg"] = _lerp_toward_fg(bg, fg, 0.16)
    palette["toolbar_fg"] = fg
    return palette


# Flexoki's real published values (stephango.com/flexoki, verified live
# 2026-07-24) -- now Standard light/dark directly, not a separate
# option (Devin, 2026-07-25). Accent color swapped from Flexoki's own
# blue (#205ea6) to Inkbone's green same day, real live feedback:
# "only request for standard is to use inkbone green instead of blue
# for standard if possible" -- green is Slate's real house accent now,
# shared across Standard and Inkbone; Solarized keeps its own blue
# identity untouched (not asked to change).
#
# bg/button_bg lightened off the real Flexoki spec, same day, second
# real ask after seeing it live: real Flexoki bg (#1c1b1a) IS
# numerically lighter than Inkbone Dark's bg (#0e0c0a) -- confirmed,
# a real ~14-unit-per-channel gap -- but Devin asked again after
# looking at it running ("make standard dark lighter in contrast to
# inkbone dark"), meaning that gap doesn't read as different enough on
# an actual screen. Live perception wins over a first-pass "the numbers
# already differ" answer -- same class of override as the Solarized
# saga this same session, just resolved in the opposite direction
# (there, a later explicit "match official spec" instruction won over
# an earlier aesthetic tweak; here, a SECOND live look overrides a
# FIRST "no change needed, already on spec" verdict). entry_bg
# (#100f0f, real Flexoki's own deliberately-darker input-field tone)
# stays untouched -- this is about the general page/chrome tone Devin
# was actually looking at, not that separate, intentional design
# choice.
_STANDARD_DARK = {
    "bg": "#3a3937", "fg": "#e6e4d9", "button_bg": "#484744",
    "entry_bg": "#100f0f", "canvas_bg": "#3a3937",
    "select_bg": "#62a945", "muted_fg": "#6f6e69", "is_dark": True,
    "highlight_bg": "#62a945",
}
_STANDARD_LIGHT = {
    "bg": "#fffcf0", "fg": "#100f0f", "button_bg": "#f2f0e5",
    "entry_bg": "#fffcf0", "canvas_bg": "#fffcf0",
    "select_bg": "#4a7637", "muted_fg": "#b7b5ac", "is_dark": False,
    "highlight_bg": "#4a7637",
}

# Solarized -- RETIRED 2026-07-29 (Devin: "Solarized can go away") --
# superseded by Slate's own dark variant below, which already carries
# these exact official neutrals (bg/button_bg/muted_fg/fg) with a moss
# accent instead of Solarized's blue. Kept as a one-line historical note,
# not a dict: the real values live in _SLATE_DARK now.

# Slate -- Runestone's slate.css (named "Mosscairn" through 2026-07-29,
# consolidated that same day from mosscairn/mosscairn2/mosscairn3 --
# three iterations landing on one real theme, "these colors are looking
# GREAT" -- then renamed once more, same day, per Devin's direct ask:
# "or just Slate," "super perfect themes, i'm so proud of these 3 custom
# themes"). Light stone carried forward from the file's own iteration;
# dark built on REAL official Solarized neutrals (bg/button_bg/muted_fg/
# fg -- ethanschoonover.com/solarized) with the accent replaced: the old
# yellow-green "lamp" desaturated and re-hued to true moss (h:95 s:40%
# l:44% -> #699d43), per Fable's steer "pull saturation well under half,
# walk hue toward true green." Solarized's own bones wearing Cairn's own
# accent ("Slate dark = solarized dark basically (desaturaized)") -- and
# per Devin's same-day ask, this dark variant also retires the old
# separate "solarized" theme entirely (redundant once this existed).
_SLATE_DARK = {
    # muted_fg corrected 2026-07-29: was #586e75 (Solarized base01, the
    # CSS file's own --text-faint) -- a real hand-transcription slip
    # caught by css_theme.py's parser reading the actual file, which
    # resolves Slate's muted_fg from the CSS's own --text-muted property
    # (base00, #657b83). test_css_theme.py's live-file check (skipped if
    # Runestone isn't present) guards against this recurring silently.
    "bg": "#002b36", "fg": "#839496", "button_bg": "#073642",
    "entry_bg": "#073642", "canvas_bg": "#002b36",
    "select_bg": "#699d43", "muted_fg": "#657b83", "is_dark": True,
    "highlight_bg": "#699d43",
}
_SLATE_LIGHT = {
    # Darkened a smidge + de-tanned 2026-07-29 per Devin's direct live
    # feedback -- re-derived from slate.css's real current light block.
    "bg": "#d0cbbf", "fg": "#13120f", "button_bg": "#c1bcad",
    "entry_bg": "#d0cbbf", "canvas_bg": "#d0cbbf",
    "select_bg": "#58763a", "muted_fg": "#322f28", "is_dark": False,
    "highlight_bg": "#58763a",
}

# Bonepaper -- merged 2026-07-29 (Devin: "make inkrain the dark mode for
# Boneink... just 3 core themes still... update boneink to 'inkrain'"),
# then renamed from "Inkrain" to "Bonepaper" that same day per Devin's
# stated preference ("i prefer bonepaper..."). Was briefly two separate
# families (Boneink and Inkrain existed side by side for about twenty
# minutes) before Devin folded them into one.
#
# Light = Boneink's real light half, UNCHANGED (bone-paper, real fixed
# teal-jade accent ~158deg -- originally read directly from boneink.css;
# see fossil history for that file's own real-values provenance and the
# jade/Inkbone-green collision it was corrected for).
#
# Dark = Inkrain's real sampled night-rain values, UNCHANGED (numpy over
# 5 branding/big/ Revelation-imagery photos, not picked by eye) --
# replaces what used to be Boneink's own jade-dark outright, not a blend.
#
# Inkrain's own short-lived standalone light half (a designed newsprint
# companion, not sampled, built minutes before this merge) is retired
# along with it -- Boneink's real light wins the slot instead. Roster is
# 3 core families: Standard, Bonepaper, Slate.
_BONEPAPER_DARK = {
    "bg": "#030302", "fg": "#e4fadf", "button_bg": "#0a0d09",
    "entry_bg": "#030302", "canvas_bg": "#030302",
    "select_bg": "#b5deb4", "muted_fg": "#8a9884", "is_dark": True,
    "highlight_bg": "#b5deb4",
}
_BONEPAPER_LIGHT = {
    "bg": "#c9b08a", "fg": "#201811", "button_bg": "#bea179",
    "entry_bg": "#c9b08a", "canvas_bg": "#c9b08a",
    "select_bg": "#2d765b", "muted_fg": "#503f2d", "is_dark": False,
    "highlight_bg": "#2d765b",
}

THEMES = {
    "light": _with_chrome_cascade(_STANDARD_LIGHT),
    "dark": _with_chrome_cascade(_STANDARD_DARK),
    "slate_light": _with_chrome_cascade(_SLATE_LIGHT),
    "slate_dark": _with_chrome_cascade(_SLATE_DARK),
    "bonepaper_light": _with_chrome_cascade(_BONEPAPER_LIGHT),
    "bonepaper_dark": _with_chrome_cascade(_BONEPAPER_DARK),
}

# Display label -> internal THEMES key, in menu order. Devin's stated
# work order 2026-07-25 ("in order: Standard, Inkbone, Solarized")
# applied as the real menu order at the time. Since then, same-session
# roster history: Solarized retired ("Solarized can go away" -- Slate
# Dark already covers its ground); Inkbone retired ("let's get rid of
# inkbone" -- shared Boneink's exact bg/fg bones); Mosscairn3 -> Mosscairn
# -> Slate (dropped the number, then dropped the name too: "these colors
# are looking GREAT" / "or just Slate"); Boneink and Inkrain existed as
# two separate families for about twenty minutes, then merged into one
# under the Inkrain name ("make inkrain the dark mode for Boneink...
# update boneink to 'inkrain'") -- Boneink's real light half survives
# inside it, Inkrain's real sampled dark half replaces Boneink's own
# jade-dark outright -- then renamed Inkrain -> Bonepaper same day
# ("i prefer bonepaper..."). Final roster: Standard, Bonepaper, Slate,
# light/dark each -- 3 core families, back down from the brief 4-family
# peak.
THEME_LABELS = {
    "Slate Light": "slate_light",
    "Slate Dark": "slate_dark",
    "Bonepaper Light": "bonepaper_light",
    "Bonepaper Dark": "bonepaper_dark",
    # Renamed from "Flexoki" (2026-07-29, Devin: "no need to mention
    # Kepano anymore as the theme name is now directly kepano... no
    # dancing around the bush, suckless") -- values are still literally
    # Flexoki, Steph Ango's (Kepano) real published palette, unchanged;
    # only the display label points straight at the person now instead
    # of the palette's own project name.
    "Kepano Light": "light",
    "Kepano Dark": "dark",
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
