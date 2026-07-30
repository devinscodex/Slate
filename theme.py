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
    #
    # select_bg/highlight_bg re-hued 2026-07-30 -- Devin, live, right
    # after the Bonepaper Light re-hue: "i like that olive green more
    # than the teal on slate light." Reused the exact same #33762d
    # (not just a similar shift) -- direct preference for that specific
    # tone, not a generic de-tealing pass.
    "bg": "#d0cbbf", "fg": "#13120f", "button_bg": "#c1bcad",
    "entry_bg": "#d0cbbf", "canvas_bg": "#d0cbbf",
    "select_bg": "#33762d", "muted_fg": "#322f28", "is_dark": False,
    "highlight_bg": "#33762d",
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
    # select_bg/highlight_bg re-hued 2026-07-30 -- Devin, live feedback:
    # "too teal, less green like in the branding." Old #2d765b (h:158,
    # jade) had B(0x5b=91) higher than R(0x2d=45), a real cyan/teal cast;
    # re-hued toward the app's own confirmed house green (#62a945, the
    # "permanent Slate accent" used on the About page, h:~103) by
    # roughly swapping the R/B channels -- same G brightness (0x76=118,
    # unchanged) so the accent reads at the same weight, B dropped
    # 91->45 and R raised 45->51 to kill the teal cast outright rather
    # than a partial nudge. Core color, carries through selection
    # highlight/checked-toggle-fill/TOC-highlight everywhere this theme
    # is active, not a one-off.
    "bg": "#c9b08a", "fg": "#201811", "button_bg": "#bea179",
    "entry_bg": "#c9b08a", "canvas_bg": "#c9b08a",
    "select_bg": "#33762d", "muted_fg": "#503f2d", "is_dark": False,
    "highlight_bg": "#33762d",
}

# MEG -- new 2026-07-30 (Devin: "whatever you wanna name our Martin
# Energy Group one"). Named "MEG", not "Martin" -- Devin, same session,
# live: "Martin Construction can suck it, i hate Martin's Blue Team,
# we're green team all the way!!" -- "Martin" alone collides with an
# unrelated company Devin has real beef with; MEG is the company's own
# actual internal shorthand and sidesteps the collision outright. Every
# value below is a REAL, verified MEG brand color, not picked by eye:
#   - select_bg/highlight_bg #62A945 and the dark-mode bg/button_bg/fg
#     stack (#1B2224/#24272a/#cfcfcb) come straight from
#     presentation/meg-theme.css, itself pulled 2026-07-22 via curl from
#     martinenergygroup.com's live Elementor global palette -- real
#     screen-native RGB, not a print approximation.
#   - muted_fg (light) #535353 is that same file's real body-text gray.
#   - Deliberately did NOT derive from the official brand PDF's Pantone
#     364/369 CMYK values (branding/MartinEnergyBrandStandards_26.pdf,
#     read live this session) -- naive CMYK->RGB on saturated greens
#     reliably oversaturates (checked: Pantone 369's CMYK converts to a
#     neon #50f205, nothing like the real site's #62A945), a known trap,
#     not a shortcut worth taking when a verified screen value already
#     exists for the same brand.
#   - Light mode's bg/entry/canvas (#FFFFFF) and button_bg (#F9F9F9) are
#     that file's real light-surface pair; fg (#1B2224) reuses the same
#     near-black "accent" the dark mode uses for bg, MEG's own solid
#     charcoal rather than the lighter #535353 body-gray (right for
#     prose on a slide, too low-contrast as this app's primary text).
#   - select_bg/highlight_bg split 2026-07-30 (Devin, live: "kinda
#     pointless... our 3 core styles have more [personality] than
#     MEG's" -> "add more spark/personality/energy to MEG light/dark"
#     -> "green" -> "more MEG"). Every other family's select_bg and
#     highlight_bg are the same single value; MEG was too, which was
#     exactly the flatness Devin called out -- one accent color
#     repeated everywhere reads generic regardless of which color it
#     is. Fix uses TWO real, verified MEG brand greens for two
#     different jobs instead of inventing a new color: select_bg stays
#     the bright primary #62A945 (checked-toggle fill -- an active
#     "you selected this" state should read energetic); highlight_bg
#     becomes the real secondary "Dark Green" #4A7637 (text selection/
#     TOC highlight -- a sustained-attention state reads better as the
#     deeper, more professional tone, not the same neon-bright pop).
#     Both colors are straight off presentation/meg-theme.css's real
#     --meg-primary/--meg-secondary, same source as everything else in
#     this family -- still exactly "green," per Devin's own answer.
_MEG_LIGHT = {
    "bg": "#ffffff", "fg": "#1b2224", "button_bg": "#f9f9f9",
    "entry_bg": "#ffffff", "canvas_bg": "#ffffff",
    "select_bg": "#62a945", "muted_fg": "#535353", "is_dark": False,
    "highlight_bg": "#4a7637",
}
_MEG_DARK = {
    "bg": "#1b2224", "fg": "#cfcfcb", "button_bg": "#24272a",
    "entry_bg": "#1b2224", "canvas_bg": "#1b2224",
    "select_bg": "#62a945", "muted_fg": "#7e8180", "is_dark": True,
    "highlight_bg": "#4a7637",
}

THEMES = {
    "light": _with_chrome_cascade(_STANDARD_LIGHT),
    "dark": _with_chrome_cascade(_STANDARD_DARK),
    "slate_light": _with_chrome_cascade(_SLATE_LIGHT),
    "slate_dark": _with_chrome_cascade(_SLATE_DARK),
    "bonepaper_light": _with_chrome_cascade(_BONEPAPER_LIGHT),
    "bonepaper_dark": _with_chrome_cascade(_BONEPAPER_DARK),
    "meg_light": _with_chrome_cascade(_MEG_LIGHT),
    "meg_dark": _with_chrome_cascade(_MEG_DARK),
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
    # Renamed BACK to "Flexoki" 2026-07-30 (Devin, live screenshot:
    # "Kepano needs to be 'Flexoki'") -- reverses the 2026-07-29 rename
    # above. Values untouched either way, always were and still are
    # Steph Ango's real published Flexoki palette (stephango.com/flexoki)
    # -- only the display label changed, back to the palette's own
    # project name instead of the person's.
    "Flexoki Light": "light",
    "Flexoki Dark": "dark",
    # New 2026-07-30 -- real Martin Energy Group brand colors, see
    # _MEG_LIGHT/_MEG_DARK's own comment for full sourcing.
    "MEG Light": "meg_light",
    "MEG Dark": "meg_dark",
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
