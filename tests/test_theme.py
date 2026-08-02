import theme


def test_get_palette_returns_light_and_dark():
    assert theme.get_palette("dark") == theme.DARK
    assert theme.get_palette("light") == theme.LIGHT


def test_get_palette_falls_back_to_default_for_unknown_name():
    assert theme.get_palette("not-a-real-theme") == theme.THEMES[theme.DEFAULT_THEME]


def test_default_theme_is_slate_light_per_devins_explicit_request():
    """Supersedes the earlier 2026-07-17 "plain Dark" ruling, the
    2026-07-25 "inkbone-dark will be our default" ruling, and the
    2026-07-29 "slate_dark" ruling (back when this family was still
    named Mosscairn, "these colors are looking GREAT"). Devin's final
    call same day, after seeing the full renamed roster live:
    "starting/defaulting to Slate light, that stone look.\""""
    assert theme.DEFAULT_THEME == "slate_light"


def test_all_themes_have_the_same_keys():
    keys = set(theme.LIGHT.keys())
    for name, palette in theme.THEMES.items():
        assert set(palette.keys()) == keys, name


def test_dark_and_light_backgrounds_are_actually_different():
    assert theme.LIGHT["bg"] != theme.DARK["bg"]
    assert theme.LIGHT["canvas_bg"] != theme.DARK["canvas_bg"]


def test_every_theme_label_maps_to_a_real_theme():
    for label, name in theme.THEME_LABELS.items():
        assert name in theme.THEMES, label


def test_roster_is_exactly_eight_themes():
    """Devin, 2026-07-25: "make standard light/dark modes the same as
    Flexoki, and get rid of Flexoki as a separate option, also delete
    Gruvbox themes... main will be Dark/Light, Solarized Light/Dark,
    Inkbone Light/Dark." Down from 5 families (10 variants) to 3
    families (6). Same day, later: "please delete solarized light
    color, just leave solarized dark and call it just 'solarized'" --
    Solarized drops to a single variant, roster was 5 total.

    Grown to 9, 2026-07-29 (WebUI/CSS council): Boneink (light/dark) and
    Mosscairn3 (light/dark) added as real candidates, Mosscairn3 ->
    Mosscairn (dropped the number), Solarized and Inkbone both retired
    (their ground covered by Mosscairn Dark and Boneink respectively).
    Inkrain then added, dark-only at first (real branding-imagery batch),
    given a real designed light half minutes later. Peaked at 9, briefly
    8 -- then Boneink and Inkrain, which had existed as two separate
    families for about twenty minutes, were merged into one under the
    Inkrain name ("make inkrain the dark mode for Boneink... just 3 core
    themes still... update boneink to 'inkrain'"): Boneink's real light
    half survives inside Inkrain, Inkrain's real sampled dark half
    replaces Boneink's own jade-dark, and Inkrain's own short-lived
    newsprint light is retired.

    Same day, once more: both surviving custom families were renamed
    (Mosscairn -> Slate, "or just Slate"; Inkrain -> Bonepaper, "i
    prefer bonepaper..."), and Standard's own label renamed to Flexoki
    (it always carried Flexoki's real published values directly, so the
    label now says what it is). Devin's final display order: Slate,
    Bonepaper, Flexoki. Final roster: Flexoki/Bonepaper/Slate, light/
    dark each, 6 total -- 3 core families, same count Devin asked for
    after the very first roster consolidation.

    Grown to 8, 2026-07-30: MEG (light/dark) added, real verified Martin
    Energy Group brand colors (see theme.py's own _MARTIN_LIGHT/
    _MARTIN_DARK comment for full sourcing) -- named "MEG" specifically,
    not "Martin" (Devin, same day: "Martin Construction can suck it... we're
    green team all the way!!" -- the bare name collides with an unrelated
    company he has real beef with). Same day, Standard's own display
    label reverted "Kepano" (a brief 2026-07-29 rename) back to
    "Flexoki", its original real source name. Renamed 2026-07-31, several
    times same day: MEG -> Anthracite -> Gridpaper -> Graphpaper ->
    **Martin** (Devin's final call, explicit override of the exact
    collision concern above -- flagged, confirmed twice anyway). Values
    unchanged through every rename.

    Gotham (real Alacritty theme, dark-only) added and removed same day,
    2026-07-31 -- roster stays at 8 (see theme.py's own THEME_LABELS
    comment for the full add/remove note)."""
    assert set(theme.THEMES.keys()) == {
        "light", "dark",
        "slate_light", "slate_dark",
        "bonepaper_light", "bonepaper_dark",
        "martin_light", "martin_dark",
    }
    for gone in ("flexoki_dark", "flexoki_light", "gruvbox_dark", "gruvbox_light",
                 "solarized_light", "solarized", "mosscairn3_light", "mosscairn3_dark",
                 "inkbone_light", "inkbone_dark", "boneink_light", "boneink_dark",
                 "mosscairn_light", "mosscairn_dark", "inkrain_light", "inkrain_dark",
                 "meg_light", "meg_dark", "anthracite_light", "anthracite_dark",
                 "gridpaper_light", "gridpaper_dark", "graphpaper_light", "graphpaper_dark",
                 "ossuary_light", "ossuary_dark", "gotham_dark"):
        assert gone not in theme.THEMES, gone
    for gone_label in ("Gruvbox Dark", "Gruvbox Light",
                        "Solarized Light", "Solarized Dark", "Solarized",
                        "Mosscairn3 Light", "Mosscairn3 Dark",
                        "Inkbone Light", "Inkbone Dark",
                        "Boneink Light", "Boneink Dark",
                        "Mosscairn Light", "Mosscairn Dark",
                        "Inkrain Light", "Inkrain Dark",
                        "Kepano Light", "Kepano Dark",
                        "MEG Light", "MEG Dark",
                        "Anthracite Light", "Anthracite Dark",
                        "Gridpaper Light", "Gridpaper Dark",
                        "Graphpaper Light", "Graphpaper Dark",
                        "Ossuary Light", "Ossuary Dark"):
        assert gone_label not in theme.THEME_LABELS, gone_label
    assert theme.THEME_LABELS["Martin Light"] == "martin_light"
    assert theme.THEME_LABELS["Martin Dark"] == "martin_dark"
    # The bare "Light"/"Dark" labels were themselves retired the same day
    # Standard's display name became "Flexoki" -- those two strings now
    # only exist as internal THEMES keys, never as a THEME_LABELS key.
    assert "Light" not in theme.THEME_LABELS
    assert "Dark" not in theme.THEME_LABELS


def test_standard_light_dark_carry_flexokis_real_values():
    """"make standard light/dark modes the same as Flexoki" -- real
    published values (stephango.com/flexoki, verified live 2026-07-24),
    not just "inspired by." fg is unchanged and still exactly on spec;
    dark's bg/button_bg are the one other deliberate exception besides
    accent -- see test_standard_dark_is_lightened_off_spec below for
    why (a real, repeated, live-feedback-driven deviation). Internal
    keys stay "light"/"dark" even after the display label became
    "Flexoki Light"/"Flexoki Dark" -- the values were always Flexoki's,
    only the label changed."""
    assert theme.THEMES["dark"]["fg"] == "#e6e4d9"
    assert theme.THEMES["light"]["bg"] == "#fffcf0"
    assert theme.THEMES["light"]["fg"] == "#100f0f"


def test_standard_dark_reverted_to_real_flexoki_spec_2026_07_30():
    """REVERSAL of the 2026-07-25 lightening this test used to guard
    (that entry's real reasoning kept below, for the record -- it isn't
    wrong about what happened, just no longer current). Devin,
    2026-07-30, live: "if flexoki dark could represent Kepano's flexoki
    dark at home a lil better." The original lightening was deliberate
    contrast-vs-Inkbone insurance; Inkbone is long retired (2026-07-29)
    and nothing in the current roster needs Standard/Flexoki Dark
    pushed off its own real spec anymore, so it's back on it.

    Original 2026-07-25 reasoning (for history): asked TWICE "should be
    lighter than inkbone's dark" then, after a first "already lighter,
    no change needed" answer proved wrong on a real screen, "make
    standard dark lighter in contrast to inkbone dark" again -- real
    Flexoki bg (#1c1b1a) IS numerically lighter than Inkbone Dark's bg
    (#0e0c0a) but didn't read as different enough live, so it got
    lightened further, off spec, on purpose. That's the deviation this
    test now confirms is UNDONE."""
    assert theme.THEMES["dark"]["bg"] == "#1c1b1a"  # real Flexoki base-950
    assert theme.THEMES["dark"]["button_bg"] == "#282726"  # real Flexoki base-900
    assert theme.THEMES["dark"]["entry_bg"] == "#100f0f"  # real Flexoki black, never drifted


def test_standard_uses_real_flexoki_blue_not_the_shared_house_green():
    """A same-day teal experiment (2026-07-31, live webUI parity ask)
    came and went -- reverted back to Flexoki's real published blue
    (#205EA6 light / #4385BE dark, stephango.com/flexoki) when this
    checkout synced theme_data/*.json against devs-themes's own
    canonical values (2026-08-01, secondary's reconciliation pass:
    "had drifted independently in this branch checkout... reconciled
    against primary's webUI"). Blue is the ratified value again --
    this test's job is just guarding against the shared house green
    (the 2026-07-25 swap this test has guarded against from the
    start), not re-litigating blue vs. teal."""
    assert theme.THEMES["dark"]["select_bg"] == "#4385be"
    assert theme.THEMES["dark"]["highlight_bg"] == "#4385be"
    assert theme.THEMES["light"]["select_bg"] == "#205ea6"
    assert theme.THEMES["light"]["highlight_bg"] == "#205ea6"


def test_every_theme_accent_is_minimal_pure_accent_lives_in_selection_roles_only():
    """Manga-essence pass (Devin, 2026-07-25, originally Inkbone-specific:
    "MINIMAL green, pure accent only... must NOT color tabs or chrome").
    Generalized 2026-07-29 when Inkbone retired -- the rule itself is a
    real house-wide design constraint every family (Flexoki, Bonepaper,
    Slate) actually follows, not a property unique to the retired
    theme: accent lives only in the genuine "selection" roles, select_bg
    (Listbox/Entry) and highlight_bg (text-selection highlight), never
    menubar/toolbar/tabstrip."""
    for name, colors in theme.THEMES.items():
        assert colors["select_bg"] not in (
            colors["menubar_bg"], colors["toolbar_bg"], colors["tabstrip_bg"]
        ), name


def test_named_theme_palettes_are_real_and_distinct():
    """Flexoki/Bonepaper/Slate -- confirm each is actually a distinct
    palette (not accidentally aliased to each other) and that is_dark
    matches the palette's own name.

    Checks (bg, select_bg) pairs rather than bg alone: this originally
    guarded Boneink Dark deliberately sharing Inkbone Dark's exact bg
    (#0e0c0a, real "night noir" bones on purpose). Both Inkbone and
    (after the later Boneink+Inkrain merge, then the Inkrain->Bonepaper
    rename) that exact bg value are gone now, but the pair-check is kept
    rather than reverted to a stricter bg-only check, since it's a
    strict superset (still catches a genuine copy-paste accident:
    identical bg AND identical accent) and stays correct if a future
    theme ever deliberately shares bones again."""
    assert theme.THEMES["slate_dark"]["is_dark"] is True
    assert theme.THEMES["dark"]["is_dark"] is True
    assert theme.THEMES["light"]["is_dark"] is False

    all_pairs = [(p["bg"], p["select_bg"]) for p in theme.THEMES.values()]
    assert len(all_pairs) == len(set(all_pairs))  # every theme is genuinely distinguishable


def test_no_dark_theme_has_brown_tones():
    """Devin, 2026-07-25, real correction after seeing the first chrome
    attempt (a warm tan/sepia #a8916a), originally Inkbone-specific:
    "less brown, more dark noir manga... no brown tones at all with
    dark slate plz... save those for our light mode." Generalized
    2026-07-29 when Inkbone retired -- this is a real house-wide rule
    (brown/sepia belongs in light themes only), not a property unique
    to the one retired theme it was first stated against. Every dark
    theme's colors must be a real grayscale/near-neutral or its own
    accent -- never a brown/tan hue. Cheap real check: brown/tan hues
    have R > G > B with a real gap (not true of grayscale, where
    R=G=B, nor of a green/moss/jade accent)."""
    for name, colors in theme.THEMES.items():
        if not colors["is_dark"]:
            continue
        for key, hexval in colors.items():
            if key == "is_dark" or not isinstance(hexval, str) or not hexval.startswith("#"):
                continue
            r, g, b = int(hexval[1:3], 16), int(hexval[3:5], 16), int(hexval[5:7], 16)
            is_brownish = r > g > b and (r - b) > 25
            assert not is_brownish, f"{name}.{key}={hexval} reads as a brown/tan tone, not allowed in a dark theme"


def test_chrome_cascade_is_a_real_three_step_gradient():
    """Devin, 2026-07-25: "make menu bar cascade down in color from
    window bar down to tabs, to toolbar making it aesthetic... same
    for the other 3 'core' themes." Second pass same day, real
    screenshot review: "menubar doesn't cascade in hue/darkness" --
    the original bg/button_bg-anchored formula produced a
    mathematically-real but PERCEPTUALLY INVISIBLE step for
    inkbone_dark (both tones too close to pure black). Real fix:
    interpolate toward fg instead (0%/8%/16%), which rides the
    theme's own guaranteed bg<->fg contrast -- one consistent rule for
    all 6 variants, and this test proves the 3 steps are ACTUALLY
    distinct by a real, non-trivial margin, not just non-equal."""
    for name, colors in theme.THEMES.items():
        assert colors["menubar_bg"] == colors["bg"], name
        assert colors["tabstrip_bg"] == theme._lerp_toward_fg(colors["bg"], colors["fg"], 0.08), name
        assert colors["toolbar_bg"] == theme._lerp_toward_fg(colors["bg"], colors["fg"], 0.16), name

        # Real perceptual guard, not just "the 3 hex strings differ" --
        # every step's total RGB distance from the previous one must
        # clear a real minimum, catching the exact class of bug this
        # pass fixed (technically-distinct but visually-identical steps).
        def rgb_distance(hex_a, hex_b):
            a, b = theme._hex_to_rgb(hex_a), theme._hex_to_rgb(hex_b)
            return sum(abs(x - y) for x, y in zip(a, b))

        assert rgb_distance(colors["menubar_bg"], colors["tabstrip_bg"]) >= 10, name
        assert rgb_distance(colors["tabstrip_bg"], colors["toolbar_bg"]) >= 10, name


def test_midpoint_computes_a_real_rgb_average():
    assert theme._midpoint("#000000", "#ffffff") == "#7f7f7f"
    assert theme._midpoint("#102030", "#102030") == "#102030"


def test_lerp_toward_fg_computes_a_real_fractional_step():
    assert theme._lerp_toward_fg("#000000", "#ffffff", 0.0) == "#000000"
    assert theme._lerp_toward_fg("#000000", "#ffffff", 1.0) == "#ffffff"
    assert theme._lerp_toward_fg("#000000", "#ffffff", 0.5) == "#808080"


def test_slate_dark_matches_the_real_official_solarized_bones():
    """Originally test_solarized_matches_the_real_official_palette
    (Devin, 2026-07-25: "please review the solarized light/dark...
    refer to official repos/color palette for it" -- real values,
    ethanschoonover.com/solarized, verified live: base03:base0 for
    bg:fg, base02 for the secondary/UI surface).

    Solarized itself was retired 2026-07-29 ("Solarized can go away")
    once this family existed (named Mosscairn at the time, then renamed
    to Slate same day, "or just Slate"), carrying these exact same
    official neutrals with a moss accent instead of blue -- this test
    moved with the values rather than being deleted, so official-
    palette fidelity for bg/button_bg/fg/muted_fg is still checked
    live. Only select_bg differs on purpose now: Slate's own moss
    accent (#699d43), not Solarized's official blue -- that
    substitution IS the whole point of this theme, not a regression.

    muted_fg corrected 2026-07-29 (#586e75 -> #657b83): css_theme.py's
    parser, reading the real slate.css (named mosscairn.css at the
    time), caught that Slate's own muted_fg had been hand-copied from
    --text-faint (base01) instead of the property it's actually meant
    to mirror, --text-muted (base00) -- see theme.py's own _SLATE_DARK
    comment for the full story.

    bg/canvas_bg moved off stock Solarized 2026-07-31 -- Devin: "i do
    like that theme for our Slate Dark," referring to Solarized Osaka
    (craftzdog/solarized-osaka.nvim, real values pulled from Devin's own
    Alacritty config, not memory). Osaka's real `black` (#073642) and
    `foreground` (#839496) already matched Slate Dark's button_bg/fg
    exactly -- only Osaka's deeper primary background (#001a1d vs stock
    Solarized's #002b36) actually differs, so that's the only value that
    moved. button_bg/fg/muted_fg/select_bg all still real official
    Solarized-lineage values, unchanged."""
    dark = theme.THEMES["slate_dark"]
    assert dark["bg"] == "#001a1d"  # Solarized Osaka's real primary background
    assert dark["button_bg"] == "#073642"  # Solarized base02 (== Osaka's own "black")
    assert dark["fg"] == "#839496"  # Solarized base0 (== Osaka's own "foreground")
    assert dark["muted_fg"] == "#657b83"  # Solarized base00 (--text-muted, not --text-faint)
    assert dark["select_bg"] == "#699d43"  # Slate's own moss accent, not Solarized's blue
