import theme


def test_get_palette_returns_light_and_dark():
    assert theme.get_palette("dark") == theme.DARK
    assert theme.get_palette("light") == theme.LIGHT


def test_get_palette_falls_back_to_default_for_unknown_name():
    assert theme.get_palette("not-a-real-theme") == theme.THEMES[theme.DEFAULT_THEME]


def test_default_theme_is_slate_light_per_devins_explicit_request():
    """The default theme has changed several times over the project's
    history (plain Dark, then Inkbone Dark, then Slate Dark, back when
    that family was still named Mosscairn) before settling on Slate
    Light as the final choice."""
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
    """The theme roster has gone through several rounds of consolidation
    and renaming. It started as 5 families (10 variants: Dark/Light,
    Gruvbox, Solarized, Inkbone, Flexoki-as-Standard), was cut down to
    Dark/Light + Solarized Light/Dark + Inkbone Light/Dark, then
    Solarized was further trimmed to a single dark-only variant.

    The roster later grew as Boneink and Mosscairn3 were added as
    candidates; Mosscairn3 was renamed to Mosscairn, and Solarized and
    Inkbone were both retired since their ground was covered by
    Mosscairn Dark and Boneink respectively. Inkrain was added dark-only
    at first and then given a designed light half. Boneink and Inkrain,
    which had briefly existed as two separate families, were merged into
    one under the Inkrain name: Boneink's light half survives inside
    Inkrain, Inkrain's own sampled dark half replaces Boneink's jade-dark,
    and Inkrain's short-lived newsprint light was retired.

    Both surviving custom families were then renamed a final time
    (Mosscairn -> Slate, Inkrain -> Bonepaper), and Standard's display
    label was renamed to Flexoki since it always carried Flexoki's
    published values directly. Final roster at that point: Flexoki/
    Bonepaper/Slate, light/dark each, 6 total -- 3 core families.

    MEG (light/dark) was then added: verified Martin Energy Group brand
    colors (see theme.py's own _MARTIN_LIGHT/_MARTIN_DARK comment for
    full sourcing), named "MEG" rather than "Martin" to avoid colliding
    with an unrelated company of the same bare name. Standard's own
    display label was reverted from a brief "Kepano" rename back to
    "Flexoki", its original source name. The MEG family itself was later
    renamed several times (MEG -> Anthracite -> Gridpaper -> Graphpaper
    -> Martin), with the original name-collision concern re-evaluated
    and the Martin name confirmed anyway. Values stayed unchanged through
    every rename.

    Gotham (an Alacritty theme, dark-only) was added and removed in the
    same pass -- roster stays at 8 (see theme.py's own THEME_LABELS
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
    """Standard's light/dark modes carry Flexoki's actual published
    values (stephango.com/flexoki), not just colors "inspired by" it.
    fg is unchanged and still exactly on spec; dark's bg/button_bg are
    the one other deliberate exception besides accent -- see
    test_standard_dark_is_lightened_off_spec below for why. Internal
    keys stay "light"/"dark" even after the display label became
    "Flexoki Light"/"Flexoki Dark" -- the values were always Flexoki's,
    only the label changed.

    light bg/button_bg were later updated to a webUI-parity variant,
    #fdf6dc/#eee2c9, rather than the stock stephango.com paper/base-50
    (#fffcf0/#f2f0e5) -- fg stays on spec either way."""
    assert theme.THEMES["dark"]["fg"] == "#e6e4d9"
    assert theme.THEMES["light"]["bg"] == "#fdf6dc"
    assert theme.THEMES["light"]["fg"] == "#100f0f"


def test_standard_dark_reverted_to_real_flexoki_spec_2026_07_30():
    """REVERSAL of an earlier lightening this test used to guard (that
    entry's original reasoning kept below, for the record -- it isn't
    wrong about what happened, just no longer current). The original
    lightening was deliberate contrast-vs-Inkbone insurance; Inkbone is
    long retired and nothing in the current roster needs Standard/
    Flexoki Dark pushed off its own spec anymore, so it's back on it,
    to better represent Flexoki's dark theme as it appears elsewhere.

    Original reasoning (for history): Flexoki's real bg (#1c1b1a) IS
    numerically lighter than Inkbone Dark's bg (#0e0c0a) but didn't read
    as different enough on screen, so it got lightened further, off
    spec, on purpose. That's the deviation this test now confirms is
    UNDONE."""
    assert theme.THEMES["dark"]["bg"] == "#1c1b1a"  # real Flexoki base-950
    assert theme.THEMES["dark"]["button_bg"] == "#282726"  # real Flexoki base-900
    assert theme.THEMES["dark"]["entry_bg"] == "#100f0f"  # real Flexoki black, never drifted


def test_standard_uses_real_flexoki_teal_not_the_shared_house_green():
    """Standard's accent went through a teal experiment for webUI parity
    (changing Kepano's accent from blue to dark teal), briefly reverted
    to Flexoki's published blue, then landed for real as teal once
    theme_data/*.json was synced against the current webUI/devs-themes
    values: #24837B light / #3AA99F dark -- still Flexoki's own
    published palette (its cyan swatch, --color-cyan), just not the one
    originally picked as the interactive accent. This test's job is just
    guarding against the shared house green this test has guarded
    against from the start, not blue vs. teal."""
    assert theme.THEMES["dark"]["select_bg"] == "#3aa99f"
    assert theme.THEMES["dark"]["highlight_bg"] == "#3aa99f"
    assert theme.THEMES["light"]["select_bg"] == "#24837b"
    assert theme.THEMES["light"]["highlight_bg"] == "#24837b"


def test_every_theme_accent_is_minimal_pure_accent_lives_in_selection_roles_only():
    """This rule originated as an Inkbone-specific constraint (minimal
    green, pure accent only, must not color tabs or chrome) and was
    later generalized when Inkbone retired -- it's a house-wide design
    constraint every family (Flexoki, Bonepaper, Slate) actually
    follows, not a property unique to the retired theme: accent lives
    only in the genuine "selection" roles, select_bg (Listbox/Entry)
    and highlight_bg (text-selection highlight), never menubar/toolbar/
    tabstrip."""
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
    """This rule was originally Inkbone-specific, a correction after an
    early chrome attempt used a warm tan/sepia (#a8916a) that read as
    too "brown" for a dark noir look, with brown tones reserved for
    light mode instead. Generalized when Inkbone retired -- this is a
    house-wide rule (brown/sepia belongs in light themes only), not a
    property unique to the one retired theme it was first stated
    against. Every dark theme's colors must be a grayscale/near-neutral
    or its own accent -- never a brown/tan hue. Cheap check: brown/tan
    hues have R > G > B with a real gap (not true of grayscale, where
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


def test_every_theme_has_a_real_second_accent_distinct_from_the_primary():
    """Slate previously felt like it had fewer colors than the webUI and
    Obsidian versions -- traced to select_bg == highlight_bg in 3 of 4
    families (only Martin already had two distinct greens). accent2 is
    a genuine second color per family, used for search-match emphasis
    (see _draw_search_highlights_for_page in slate.py) -- every family's
    own comment in theme.py documents where its specific value came
    from (never invented).

    Widened further: the first accent2 pass for Martin reused
    highlight_bg's own value outright (distinct from select_bg, but now
    IDENTICAL to highlight_bg -- just relocated the duplicate instead
    of removing it). accent2 must be pairwise distinct from BOTH other
    accent roles, not just select_bg.

    select_bg == highlight_bg still holds for Bonepaper/Standard/Slate
    (only Martin ever had two distinct greens) -- deliberately NOT
    changed here. That pairing is a documented, already-shipped design
    choice for those 3 families (theme.py's own history: "carries
    through selection highlight/checked-toggle-fill/TOC-highlight
    everywhere this theme is active, not a one-off") and highlight_bg
    also drives live text-selection + saved-PDF-highlight-annotation
    color, tested behavior this pass isn't touching. Whether "no repeat
    colors" also means reversing THAT pairing is a real open question,
    not a call to make silently here."""
    for name, colors in theme.THEMES.items():
        assert "accent2" in colors, name
        assert colors["select_bg"] != colors["accent2"], f"{name}: select_bg == accent2"
        assert colors["highlight_bg"] != colors["accent2"], f"{name}: highlight_bg == accent2"


def test_chrome_cascade_is_a_real_three_step_gradient():
    """The menu bar cascades down in color from window bar to tabs to
    toolbar for an aesthetic gradient effect. tabstrip_bg/toolbar_bg are
    each family's own authored bg2/bg3 (real values pulled from webUI's
    own CSS, not a generic computed lerp) -- a family whose identity is
    "true black, color reserved for the accent" (bonepaper dark)
    authors a near-invisible step here on purpose, so this test checks
    the cascade actually READS the authored values (not a stale
    computed fallback), plus a real perceptual guard that catches a
    theme accidentally shipping a technically-distinct but visually-
    identical step."""
    for name, colors in theme.THEMES.items():
        assert colors["menubar_bg"] == colors["bg"], name
        assert colors["tabstrip_bg"] == colors["bg2"], name
        assert colors["toolbar_bg"] == colors["bg3"], name

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


def test_slate_dark_matches_the_real_official_nord_palette():
    """Slate Dark was rebuilt on the real published Nord palette
    (nordtheme.com) -- Polar Night bg/button_bg/entry_bg (nord0/nord2/
    nord1), Snow Storm fg (nord4), Frost select_bg/highlight_bg (nord8/
    nord9, two distinct blues so the two roles don't collide), Polar
    Night nord3 for muted_fg/border. Checked against the real published
    hex values, not re-derived or approximated.

    Previously built on Solarized/Solarized-Osaka neutrals with a moss
    accent (that lineage is gone now, not just re-hued) -- see git
    history for the prior Solarized-fidelity version of this test if
    that lineage is ever needed again."""
    dark = theme.THEMES["slate_dark"]
    assert dark["bg"] == "#2e3440"  # Nord0 (Polar Night)
    assert dark["button_bg"] == "#434c5e"  # Nord2
    assert dark["entry_bg"] == "#3b4252"  # Nord1
    assert dark["fg"] == "#d8dee9"  # Nord4 (Snow Storm)
    assert dark["muted_fg"] == "#4c566a"  # Nord3
    assert dark["select_bg"] == "#88c0d0"  # Nord8 (Frost)
    assert dark["highlight_bg"] == "#81a1c1"  # Nord9 (Frost) -- distinct from select_bg
    assert dark["accent2"] == "#b48ead"  # Nord15 (Aurora purple)
