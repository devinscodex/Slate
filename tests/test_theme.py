import theme


def test_get_palette_returns_light_and_dark():
    assert theme.get_palette("dark") == theme.DARK
    assert theme.get_palette("light") == theme.LIGHT


def test_get_palette_falls_back_to_default_for_unknown_name():
    assert theme.get_palette("not-a-real-theme") == theme.THEMES[theme.DEFAULT_THEME]


def test_default_theme_is_mosscairn_dark_per_devins_explicit_request():
    """Supersedes the earlier 2026-07-17 "plain Dark" ruling and the
    2026-07-25 "inkbone-dark will be our default" ruling -- Inkbone
    retired 2026-07-29 ("let's get rid of inkbone"), and Devin's stated
    favorite this session ("these colors are looking GREAT") is
    Mosscairn Dark."""
    assert theme.DEFAULT_THEME == "mosscairn_dark"


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


def test_roster_is_exactly_seven_themes():
    """Devin, 2026-07-25: "make standard light/dark modes the same as
    Flexoki, and get rid of Flexoki as a separate option, also delete
    Gruvbox themes... main will be Dark/Light, Solarized Light/Dark,
    Inkbone Light/Dark." Down from 5 families (10 variants) to 3
    families (6). Same day, later: "please delete solarized light
    color, just leave solarized dark and call it just 'solarized'" --
    Solarized drops to a single variant, roster was 5 total.

    Grown to 9, 2026-07-29 (WebUI/CSS council): Boneink (light/dark) and
    Mosscairn3 (light/dark -- Solarized bones + a desaturated moss
    accent) added as real candidates. Settled the same day: Mosscairn3
    -> Mosscairn (dropped the number), Solarized RETIRED ("Solarized can
    go away" -- Mosscairn Dark already covers its ground), and Inkbone
    RETIRED too ("let's get rid of inkbone" -- Boneink already shares
    its exact bg/fg bones). Inkrain added same day (real branding-imagery
    batch, dark-only, no light half exists in the source material).
    Final roster: Standard/Boneink/Mosscairn (light/dark each) + Inkrain
    (dark only), 7 total."""
    assert set(theme.THEMES.keys()) == {
        "light", "dark",
        "boneink_light", "boneink_dark",
        "mosscairn_light", "mosscairn_dark",
        "inkrain_dark",
    }
    for gone in ("flexoki_dark", "flexoki_light", "gruvbox_dark", "gruvbox_light",
                 "solarized_light", "solarized", "mosscairn3_light", "mosscairn3_dark",
                 "inkbone_light", "inkbone_dark", "inkrain_light"):
        assert gone not in theme.THEMES, gone
    for gone_label in ("Flexoki Dark", "Flexoki Light", "Gruvbox Dark", "Gruvbox Light",
                        "Solarized Light", "Solarized Dark", "Solarized",
                        "Mosscairn3 Light", "Mosscairn3 Dark",
                        "Inkbone Light", "Inkbone Dark", "Inkrain Light"):
        assert gone_label not in theme.THEME_LABELS, gone_label


def test_standard_light_dark_carry_flexokis_real_values():
    """"make standard light/dark modes the same as Flexoki" -- real
    published values (stephango.com/flexoki, verified live 2026-07-24),
    not just "inspired by." fg is unchanged and still exactly on spec;
    dark's bg/button_bg are the one other deliberate exception besides
    accent -- see test_standard_dark_is_lightened_off_spec below for
    why (a real, repeated, live-feedback-driven deviation)."""
    assert theme.THEMES["dark"]["fg"] == "#e6e4d9"
    assert theme.THEMES["light"]["bg"] == "#fffcf0"
    assert theme.THEMES["light"]["fg"] == "#100f0f"


def test_standard_dark_is_lightened_off_spec_for_real_contrast_with_boneink():
    """Devin, 2026-07-25, asked TWICE: "should be lighter than
    inkbone's dark" then, after a first "already lighter, no change
    needed" answer proved wrong on a real screen, "make standard dark
    lighter in contrast to inkbone dark" again. Real Flexoki bg
    (#1c1b1a) IS numerically lighter than Inkbone Dark's bg (#0e0c0a,
    a genuine ~14-unit gap) but didn't read as different enough live --
    lightened further, a deliberate deviation from pure Flexoki
    fidelity. Real, verifiable minimum: at least DOUBLE the original
    spec's gap from Inkbone, not just marginally more.

    Repointed at boneink_dark 2026-07-29 (Inkbone retired, "let's get
    rid of inkbone") -- boneink_dark shares Inkbone Dark's exact bg
    (#0e0c0a, same real "night noir" bones on purpose), so the same
    contrast-fidelity check still holds against a real current theme."""
    standard_bg = theme._hex_to_rgb(theme.THEMES["dark"]["bg"])
    boneink_bg = theme._hex_to_rgb(theme.THEMES["boneink_dark"]["bg"])
    original_flexoki_bg = theme._hex_to_rgb("#1c1b1a")
    original_gap = sum(a - b for a, b in zip(original_flexoki_bg, boneink_bg))
    new_gap = sum(a - b for a, b in zip(standard_bg, boneink_bg))
    assert new_gap >= original_gap * 2
    # button_bg must still be a lighter step than the new bg (same
    # relative relationship the real spec had, just both shifted up)
    button_bg = theme._hex_to_rgb(theme.THEMES["dark"]["button_bg"])
    assert sum(button_bg) > sum(standard_bg)


def test_standard_uses_inkbone_green_not_flexoki_blue():
    """Devin, 2026-07-25, real live feedback: "only request for
    standard is to use inkbone green instead of blue for standard if
    possible." That green is now Standard's own permanent house accent
    (#62a945) even though Inkbone itself was later retired, 2026-07-29 --
    the value outlived the theme it was borrowed from. (Solarized's own
    separate blue identity was retired along with that theme too, same
    day -- see test_mosscairn_dark_matches_the_real_official_solarized_bones,
    which keeps the official-palette-fidelity check alive against
    Mosscairn Dark instead.)"""
    assert theme.THEMES["dark"]["select_bg"] == "#62a945"
    assert theme.THEMES["dark"]["highlight_bg"] == "#62a945"
    assert theme.THEMES["light"]["select_bg"] == "#4a7637"
    assert theme.THEMES["light"]["highlight_bg"] == "#4a7637"


def test_every_theme_accent_is_minimal_pure_accent_lives_in_selection_roles_only():
    """Manga-essence pass (Devin, 2026-07-25, originally Inkbone-specific:
    "MINIMAL green, pure accent only... must NOT color tabs or chrome").
    Generalized 2026-07-29 when Inkbone retired -- the rule itself is a
    real house-wide design constraint every family (Standard, Boneink,
    Mosscairn) actually follows, not a property unique to the retired
    theme: accent lives only in the genuine "selection" roles, select_bg
    (Listbox/Entry) and highlight_bg (text-selection highlight), never
    menubar/toolbar/tabstrip."""
    for name, colors in theme.THEMES.items():
        assert colors["select_bg"] not in (
            colors["menubar_bg"], colors["toolbar_bg"], colors["tabstrip_bg"]
        ), name


def test_named_theme_palettes_are_real_and_distinct():
    """Standard(Flexoki)/Boneink/Mosscairn -- confirm each is actually a
    distinct palette (not accidentally aliased to each other) and that
    is_dark matches the palette's own name.

    Checks (bg, select_bg) pairs rather than bg alone: this originally
    guarded boneink_dark deliberately sharing Inkbone Dark's exact bg
    (#0e0c0a, real "night noir" bones on purpose) -- Inkbone is retired
    now, but the pair-check is kept rather than reverted to a stricter
    bg-only check, since it's a strict superset (still catches a genuine
    copy-paste accident: identical bg AND identical accent) and stays
    correct if a future theme ever deliberately shares bones again."""
    assert theme.THEMES["mosscairn_dark"]["is_dark"] is True
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


def test_mosscairn_dark_matches_the_real_official_solarized_bones():
    """Originally test_solarized_matches_the_real_official_palette
    (Devin, 2026-07-25: "please review the solarized light/dark...
    refer to official repos/color palette for it" -- real values,
    ethanschoonover.com/solarized, verified live: base03:base0 for
    bg:fg, base02 for the secondary/UI surface).

    Solarized itself was retired 2026-07-29 ("Solarized can go away")
    once Mosscairn Dark existed, carrying these exact same official
    neutrals with a moss accent instead of blue -- this test moved
    with the values rather than being deleted, so official-palette
    fidelity for bg/button_bg/fg/muted_fg is still checked live. Only
    select_bg differs on purpose now: Mosscairn's own moss accent
    (#699d43), not Solarized's official blue -- that substitution IS
    the whole point of this theme, not a regression.

    muted_fg corrected 2026-07-29 (#586e75 -> #657b83): css_theme.py's
    parser, reading the real mosscairn.css, caught that Slate's muted_fg
    had been hand-copied from --text-faint (base01) instead of the
    property it's actually meant to mirror, --text-muted (base00) --
    see theme.py's own _MOSSCAIRN_DARK comment for the full story."""
    dark = theme.THEMES["mosscairn_dark"]
    assert dark["bg"] == "#002b36"  # Solarized base03
    assert dark["button_bg"] == "#073642"  # Solarized base02
    assert dark["fg"] == "#839496"  # Solarized base0
    assert dark["muted_fg"] == "#657b83"  # Solarized base00 (--text-muted, not --text-faint)
    assert dark["select_bg"] == "#699d43"  # Mosscairn's own moss accent, not Solarized's blue
