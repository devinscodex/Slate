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

# theme_data/*.json are pulled copies of devs-themes/palettes/*.json (the
# central source of truth, /mnt/c/bin/projects/devs-themes/README.md) --
# run pull_themes.sh to refresh. Copy, not symlink, on purpose: Slate is
# free to tweak its own copy independently without touching the shared repo.
_THEME_DATA_DIR = Path(__file__).parent / "theme_data"


_BASE_KEYS = (
    "bg", "fg", "button_bg", "entry_bg", "canvas_bg",
    "select_bg", "muted_fg", "highlight_bg",
)


def _load_base(family: str, mode: str) -> dict:
    """Loads one family's base 8-key palette (_BASE_KEYS) for the given
    mode ("light" or "dark") from theme_data/<family>.json, plus is_dark
    (not stored in the JSON itself, derived from which mode was asked
    for). Whitelisted to _BASE_KEYS on purpose: devs-themes is a
    shared repo across apps and can carry extra per-consumer keys (e.g.
    bonepaper.json's external_link, Runestone-only) that aren't part of
    Slate's own palette shape -- test_theme.py's own
    test_all_themes_have_the_same_keys caught this leaking through on
    the first pass."""
    data = json.loads((_THEME_DATA_DIR / f"{family}.json").read_text())[mode]
    return {k: data[k] for k in _BASE_KEYS} | {"is_dark": mode == "dark"}

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
    general Button widgets -- unaffected by this cascade now).

    active_tab_bg added 2026-07-31 (Devin: "can we also use clever
    hints of green for our active tabs in all themes of Slate plz?"):
    35% of the way from button_bg (the plain tab fill every OTHER tab
    still uses) toward the theme's OWN select_bg -- a real tint, not a
    full-saturation fill (which would be loud, not "clever"), and each
    family's OWN accent hue, not a forced green -- Flexoki's is its own
    real blue, matching the standing "each family keeps its own accent
    identity" rule already documented above rather than special-casing
    green everywhere "hints of green" could be read literally to mean."""
    palette = dict(palette)
    bg, fg = palette["bg"], palette["fg"]
    palette["menubar_bg"] = bg
    palette["menubar_fg"] = fg
    palette["tabstrip_bg"] = _lerp_toward_fg(bg, fg, 0.08)
    palette["toolbar_bg"] = _lerp_toward_fg(bg, fg, 0.16)
    palette["toolbar_fg"] = fg
    palette["active_tab_bg"] = _lerp_toward_fg(palette["button_bg"], palette["select_bg"], 0.35)
    # dialog_border added 2026-08-02 (Devin: "i want to capture that
    # same look" -- webUI's Bonepaper Dark uses a translucent version
    # of the theme's OWN accent for every border/edge, rgba(180,228,
    # 188,0.35), instead of a plain unrelated gray -- real signature
    # look Devin called out as "one of the coolest dark themes out
    # there... so unique." Settings/About/Sample Voices dialogs were
    # all using one fixed universal gray (#6b6b6b) regardless of theme.
    # Tk's highlightbackground has no real alpha, so this approximates
    # the same effect with a real blend instead: fg toward select_bg at
    # 35% (NOT bg toward select_bg -- checked via the same
    # _wcag_contrast_ratio helper the toggle-buttons already use: a
    # bg-anchored blend only cleared ~3:1 in slate_dark and sat under
    # 5:1 in most light themes, real risk of the border reading as
    # near-invisible against its own dialog fill, the exact "can't tell
    # where the window is" bug this border exists to prevent; fg-
    # anchored clears 3.7:1+ everywhere, most themes well past 5:1).
    palette["dialog_border"] = _lerp_toward_fg(fg, palette["select_bg"], 0.35)
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
# Real values now loaded from theme_data/flexoki.json (pulled from
# devs-themes) rather than hand-transcribed here -- see _load_base
# above. History of how these values were reached, kept for provenance:
#
# bg/button_bg reverted to real spec 2026-07-30 -- Devin, live:
# "if flexoki dark could represent Kepano's flexoki dark at home a
# lil better." Was #3a3937/#484744, a 2026-07-25 deliberate
# lightening off spec ("make standard dark lighter in contrast to
# inkbone dark") that's no longer wanted now that Inkbone is retired
# and there's nothing left to contrast against. Real values verified
# live via stephango.com/flexoki: base-950 #1C1B1A (bg), base-900
# #282726 (button_bg) -- entry_bg (#100f0f, real "black" tier)
# already matched spec and stays untouched.
#
# select_bg/highlight_bg also reverted, same ask: real Flexoki
# blue-400 #4385BE, not the shared green every other family (Slate/
# Bonepaper/MEG) uses -- the 2026-07-25 green swap is undone here
# specifically so Flexoki reads as actually Flexoki again, not a
# 4th green reskin.
_STANDARD_DARK = _load_base("flexoki", "dark") | {
    # accent2 added 2026-08-02 (Devin: search highlighting was hardcoded
    # plain yellow/red, ignoring theme entirely -- real gap found
    # investigating "Slate feels like it has less colors than webUI/
    # Runestone"). First pick was Flexoki's real orange (#da702c,
    # stephango.com/flexoki, mirrors Runestone's flexoki.css --color-
    # orange) -- caught by this file's OWN test_no_dark_theme_has_
    # brown_tones (Devin, 2026-07-25/29, standing rule: no brown/tan/
    # rust hues in ANY dark theme, ever). Orange, red, and yellow all
    # trip that same rule (they're all warm R>G>B hues, exactly the
    # category the rule bans) -- purple is Flexoki's real, own
    # published hue that ISN'T warm: --color-purple under .theme-dark.
    "accent2": "#8b7ec8",
}
# bg/fg/button_bg/muted_fg were already exact real Flexoki spec
# (paper/black/base-50/base-300, verified live via stephango.com/
# flexoki) -- never drifted, only Dark's neutrals did.
#
# select_bg/highlight_bg reverted 2026-07-30, same "represent
# Flexoki... at home" ask as Dark above: real Flexoki blue-600
# #205EA6, not the shared green. This is the same real value the
# green swap replaced back on 2026-07-25 ("only request for
# standard is to use inkbone green instead of blue") -- undone now
# that green is Slate/Bonepaper/MEG's shared identity and Flexoki
# needs its own.
_STANDARD_LIGHT = _load_base("flexoki", "light") | {
    # Real Flexoki purple-600, same source/reasoning as Dark's accent2
    # above (stephango.com/flexoki, Runestone's flexoki.css --color-
    # purple under .theme-light) -- the brown-tone rule only applies to
    # dark themes, but using the same HUE family in both modes (not
    # orange-in-light/purple-in-dark) keeps accent2 recognizable as
    # "the same second accent" across a light/dark toggle.
    "accent2": "#5e409d",
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
# Real values now loaded from theme_data/slate.json (pulled from
# devs-themes) rather than hand-transcribed here -- see _load_base
# above. History kept for provenance:
#
# muted_fg corrected 2026-07-29: was #586e75 (Solarized base01, the
# CSS file's own --text-faint) -- a real hand-transcription slip
# caught by css_theme.py's parser reading the actual file, which
# resolves Slate's muted_fg from the CSS's own --text-muted property
# (base00, #657b83). test_css_theme.py's live-file check (skipped if
# Runestone isn't present) guards against this recurring silently.
_SLATE_DARK = _load_base("slate", "dark") | {
    # accent2 added 2026-08-02, same "second color for emphasis" gap as
    # Standard's own accent2 above. Slate's own Runestone lineage
    # (slate.css/solarized-osaka.css) never defined a distinct second
    # accent the way Bonepaper/Martin do -- rather than invent a color,
    # this pulls from the SAME real published Solarized spec Slate's
    # own primary neutrals already come from (ethanschoonover.com/
    # solarized). First pick was Solarized's real orange (#cb4b16) --
    # caught by test_no_dark_theme_has_brown_tones (Devin's standing
    # no-brown-in-dark-themes rule; orange/red/yellow are all warm
    # R>G>B hues that trip it). Solarized's real magenta (#d33682)
    # isn't warm in that sense and passes clean. Solarized's accent
    # hues are identical across light and dark by the spec's own
    # design, so light/dark share this same value.
    "accent2": "#d33682",
}
# Darkened a smidge + de-tanned 2026-07-29 per Devin's direct live
# feedback -- re-derived from slate.css's real current light block.
#
# select_bg/highlight_bg re-hued 2026-07-30 -- Devin, live, right
# after the Bonepaper Light re-hue: "i like that olive green more
# than the teal on slate light." Reused the exact same #33762d
# (not just a similar shift) -- direct preference for that specific
# tone, not a generic de-tealing pass.
_SLATE_LIGHT = _load_base("slate", "light") | {
    "accent2": "#d33682",  # same real Solarized magenta as Dark above
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
# Real values now loaded from theme_data/bonepaper.json (pulled from
# devs-themes) rather than hand-transcribed here -- see _load_base
# above. Briefly renamed to "Ossuary" 2026-07-31 (Devin: "Bonepaper never
# really stuck"), reverted same day ("leave bonepaper") once the 4th
# family got renamed to "Martin" instead of "Graphpaper" -- no more
# "-paper" collision to avoid, so no reason to move off the name Devin
# already has real attachment to ("i prefer bonepaper..."). History kept
# for provenance:
_BONEPAPER_DARK = _load_base("bonepaper", "dark") | {
    # accent2 added 2026-08-02 (the specific theme Devin compared against
    # webUI/Runestone and found flat). First pick was Runestone's own
    # bonepaper.css H3-header/code-keyword coral (#d98f7a) -- real,
    # sourced, but caught by test_no_dark_theme_has_brown_tones (Devin's
    # standing no-brown-in-dark-themes rule; a warm coral is exactly what
    # it bans, even though Runestone's own Obsidian theme uses it fine --
    # different app, Slate has its own explicit, already-shipped rule to
    # respect here). bonepaper.json already carries a second real color
    # Slate never loaded: external_link (#9d8cf0 dark / #5b3fa6 light,
    # Runestone's own hyperlink color for this family) -- a genuine
    # lavender/violet, not warm, passes clean, and it's the SAME "second
    # distinct color already used elsewhere in this exact family" role
    # coral would have filled, just sourced from a different real field.
    "accent2": "#9d8cf0",
}
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
# bg/fg/button_bg/muted_fg re-derived 2026-07-30 -- Devin, live:
# "bonepaper light, if you can make a smidge more grundgier and
# 'bonier' and sepia, look to artwork for samples." Real numpy
# sampling (same methodology Bonepaper Dark was originally built
# with) over 5 images from the actual boneink/ reference folder
# (bone-cathedral, bone-circuit, broken-ribcage, beneath-the-skull,
# before-the-broke-bone-gate) -- warm mid-brightness pixels sampled
# as the "paper" candidate (#a69d7f, a real grungy olive-sepia, not
# picked by eye), near-black pixels as the "ink" candidate (#020202).
# Blended 50% from the PREVIOUS values toward these real samples --
# "a smidge," not a wholesale swap -- landing here:
_BONEPAPER_LIGHT = _load_base("bonepaper", "light") | {
    # bonepaper.json's real external_link value for light mode -- same
    # reasoning as Dark's accent2 above.
    "accent2": "#5b3fa6",
}

# MEG -- new 2026-07-30 (Devin: "whatever you wanna name our Martin
# Energy Group one"). Named "MEG", not "Martin" -- Devin, same session,
# live: "Martin Construction can suck it, i hate Martin's Blue Team,
# we're green team all the way!!" -- "Martin" alone collides with an
# unrelated company Devin has real beef with; MEG is the company's own
# actual internal shorthand and sidesteps the collision outright.
# REVERSED 2026-07-31, Devin's own explicit call after being flagged with
# this exact history ("just Martin," confirmed twice, "clean, elegant")
# -- his call to make each time, not mine to keep overriding once he's
# seen the flag and decided anyway. Every value below is a REAL, verified
# MEG brand color, not picked by eye:
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
_MARTIN_LIGHT = _load_base("martin", "light") | {
    # Real gap caught 2026-08-02 (Devin: "no theme should have any repeat
    # colors!"): first pick reused highlight_bg's own value (#4a7637)
    # outright -- distinct from select_bg, but IDENTICAL to highlight_bg,
    # just moving which duplicate pair existed rather than removing one.
    # martin.css has no 4th distinct hue at all (Martin is deliberately
    # single-hue-family -- real MEG brand green, "green team all the
    # way," per its own Pantone-collision history) -- its own real
    # link-color-hover (#3d5f2c light / #7cc25a dark) is a genuinely
    # different shade of the same green, not invented, and not equal to
    # either select_bg or highlight_bg.
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
# ("i prefer bonepaper..."). Bonepaper briefly renamed Ossuary
# 2026-07-31, reverted same day ("leave bonepaper").
#
# 4th family's own long name history, all same-day 2026-07-31: MEG ->
# Anthracite -> Gridpaper -> Graphpaper -> **Martin** (Devin's final
# call, explicit override of his own earlier "Martin Construction"
# collision concern -- flagged, confirmed twice anyway, "clean,
# elegant"). Values unchanged through every rename.
#
# Menu order, changed 2026-07-31 (Devin's explicit rule): Slate is
# always top/default; the other three sort alphabetically (Bonepaper,
# Flexoki, Martin) rather than the old ad-hoc arrival order.
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
    # Real Martin Energy Group brand colors, see _MARTIN_LIGHT/
    # _MARTIN_DARK's own comment for full sourcing and the long same-day
    # rename history (MEG -> Anthracite -> Gridpaper -> Graphpaper ->
    # Martin).
    "Martin Light": "martin_light",
    "Martin Dark": "martin_dark",
    # Gotham (real Alacritty theme, dark-only) added and removed same
    # day, 2026-07-31 -- Devin: "let's remove gotham, sorry, but... this
    # may leave room for other themes ppl may not know about." Roster
    # stays at 8; the picker redesign in progress (dropdown + light/dark
    # radios) is the real next step for surfacing more families later,
    # not another swatch-grid row.
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
