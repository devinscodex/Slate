import theme


def test_get_palette_returns_light_and_dark():
    assert theme.get_palette("dark") == theme.DARK
    assert theme.get_palette("light") == theme.LIGHT


def test_get_palette_falls_back_to_default_for_unknown_name():
    assert theme.get_palette("not-a-real-theme") == theme.THEMES[theme.DEFAULT_THEME]


def test_default_theme_is_inkbone_dark_per_devins_explicit_request():
    """Supersedes the earlier 2026-07-17 "plain Dark" ruling -- Devin,
    2026-07-25: "inkbone-dark will be our default (dark slate, heavy
    black pure night noir ink) theme."""
    assert theme.DEFAULT_THEME == "inkbone_dark"


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
    Mosscairn3 (light/dark -- Solarized bones + a desaturated moss
    accent) added as real candidates. Settled the same day, later:
    Mosscairn3 -> Mosscairn (Devin: "these colors are looking GREAT,"
    dropped the number) and Solarized RETIRED entirely ("Solarized can
    go away") -- Mosscairn Dark already carries its exact official
    neutrals with a moss accent instead of blue, made the standalone
    Solarized entry redundant. Roster settles at 8."""
    assert set(theme.THEMES.keys()) == {
        "light", "dark",
        "inkbone_light", "inkbone_dark",
        "boneink_light", "boneink_dark",
        "mosscairn_light", "mosscairn_dark",
    }
    for gone in ("flexoki_dark", "flexoki_light", "gruvbox_dark", "gruvbox_light",
                 "solarized_light", "solarized", "mosscairn3_light", "mosscairn3_dark"):
        assert gone not in theme.THEMES, gone
    for gone_label in ("Flexoki Dark", "Flexoki Light", "Gruvbox Dark", "Gruvbox Light",
                        "Solarized Light", "Solarized Dark", "Solarized",
                        "Mosscairn3 Light", "Mosscairn3 Dark"):
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


def test_standard_dark_is_lightened_off_spec_for_real_contrast_with_inkbone():
    """Devin, 2026-07-25, asked TWICE: "should be lighter than
    inkbone's dark" then, after a first "already lighter, no change
    needed" answer proved wrong on a real screen, "make standard dark
    lighter in contrast to inkbone dark" again. Real Flexoki bg
    (#1c1b1a) IS numerically lighter than Inkbone Dark's bg (#0e0c0a,
    a genuine ~14-unit gap) but didn't read as different enough live --
    lightened further, a deliberate deviation from pure Flexoki
    fidelity. Real, verifiable minimum: at least DOUBLE the original
    spec's gap from Inkbone, not just marginally more."""
    standard_bg = theme._hex_to_rgb(theme.THEMES["dark"]["bg"])
    inkbone_bg = theme._hex_to_rgb(theme.THEMES["inkbone_dark"]["bg"])
    original_flexoki_bg = theme._hex_to_rgb("#1c1b1a")
    original_gap = sum(a - b for a, b in zip(original_flexoki_bg, inkbone_bg))
    new_gap = sum(a - b for a, b in zip(standard_bg, inkbone_bg))
    assert new_gap >= original_gap * 2
    # button_bg must still be a lighter step than the new bg (same
    # relative relationship the real spec had, just both shifted up)
    button_bg = theme._hex_to_rgb(theme.THEMES["dark"]["button_bg"])
    assert sum(button_bg) > sum(standard_bg)


def test_standard_uses_inkbone_green_not_flexoki_blue():
    """Devin, 2026-07-25, real live feedback: "only request for
    standard is to use inkbone green instead of blue for standard if
    possible." Green is Slate's real house accent now, shared by
    Standard and Inkbone. (Solarized's own separate blue identity was
    retired along with the theme itself, 2026-07-29 -- see
    test_mosscairn_dark_matches_the_real_official_solarized_bones,
    which keeps the official-palette-fidelity check alive against
    Mosscairn Dark instead.)"""
    assert theme.THEMES["dark"]["select_bg"] == "#62a945"
    assert theme.THEMES["dark"]["highlight_bg"] == "#62a945"
    assert theme.THEMES["light"]["select_bg"] == "#4a7637"
    assert theme.THEMES["light"]["highlight_bg"] == "#4a7637"


def test_inkbone_dark_night_noir_page_matches_the_real_cairn_source():
    """Sourced directly from cairn/presentation/eisenhower-board-2026-07-24
    -inkbone.html's real CSS, not guessed. inkbone_light's canvas_bg
    diverged from that source in the 2026-07-25 sepia-darkening pass
    (Devin's own design call, not sourced -- see the theme.py comment
    on inkbone_light) so only the dark page is checked against it here."""
    dark = theme.THEMES["inkbone_dark"]
    assert dark["canvas_bg"] == "#0e0c0a"  # night-noir page
    assert dark["is_dark"] is True
    assert theme.THEMES["inkbone_light"]["is_dark"] is False


def test_inkbone_green_is_minimal_pure_accent_lives_in_selection_roles_only():
    """Manga-essence pass (Devin, 2026-07-25): "MINIMAL green, pure
    accent only." Second pass same day (real screenshot review): green
    must NOT color tabs or chrome (menubar/tabstrip/toolbar handle
    that now, see slate.py's _apply_theme/_apply_chrome_theme) -- it
    lives only in the genuine "selection" roles, select_bg
    (Listbox/Entry) and highlight_bg (text-selection highlight)."""
    dark = theme.THEMES["inkbone_dark"]
    assert dark["select_bg"] == "#62a945"
    assert dark["highlight_bg"] == "#62a945"
    assert dark["select_bg"] not in (dark["menubar_bg"], dark["toolbar_bg"], dark["tabstrip_bg"])

    light = theme.THEMES["inkbone_light"]
    assert light["select_bg"] == "#4a7637"
    assert light["highlight_bg"] == "#4a7637"
    assert light["select_bg"] not in (light["menubar_bg"], light["toolbar_bg"], light["tabstrip_bg"])


def test_named_theme_palettes_are_real_and_distinct():
    """Standard(Flexoki)/Inkbone/Boneink/Mosscairn -- confirm each is
    actually a distinct palette (not accidentally aliased to each
    other) and that is_dark matches the palette's own name.

    Checks (bg, select_bg) pairs rather than bg alone: boneink_dark's
    #0e0c0a is literally Inkbone Dark's bg (same real "night noir"
    bones, boneink.css was built to share them) -- a deliberate,
    on-purpose sibling, not an accident. A bare bg-uniqueness check
    would fail on that intentional pairing; checking the (bg,
    select_bg) pair still catches a genuine copy-paste accident
    (identical bg AND identical accent = truly indistinguishable
    theme, which no two here are)."""
    assert theme.THEMES["mosscairn_dark"]["is_dark"] is True
    assert theme.THEMES["dark"]["is_dark"] is True
    assert theme.THEMES["light"]["is_dark"] is False

    all_pairs = [(p["bg"], p["select_bg"]) for p in theme.THEMES.values()]
    assert len(all_pairs) == len(set(all_pairs))  # every theme is genuinely distinguishable


def test_inkbone_dark_has_no_brown_tones():
    """Devin, 2026-07-25, real correction after seeing the first chrome
    attempt (a warm tan/sepia #a8916a): "less brown, more dark noir
    manga... no brown tones at all with dark slate plz... save those
    for our light mode." Every inkbone_dark color must be a real
    grayscale/near-neutral or the green accent -- never a brown/tan hue.
    Cheap real check: brown/tan hues have R > G > B with a real gap
    (not true of grayscale, where R=G=B, or of the green accent)."""
    dark = theme.THEMES["inkbone_dark"]
    for key, hexval in dark.items():
        if key == "is_dark" or not isinstance(hexval, str) or not hexval.startswith("#"):
            continue
        r, g, b = int(hexval[1:3], 16), int(hexval[3:5], 16), int(hexval[5:7], 16)
        is_brownish = r > g > b and (r - b) > 25
        assert not is_brownish, f"{key}={hexval} reads as a brown/tan tone, not allowed in inkbone_dark"


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
