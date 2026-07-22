import theme


def test_get_palette_returns_light_and_dark():
    assert theme.get_palette("dark") == theme.DARK
    assert theme.get_palette("light") == theme.LIGHT


def test_get_palette_falls_back_to_default_for_unknown_name():
    assert theme.get_palette("not-a-real-theme") == theme.THEMES[theme.DEFAULT_THEME]


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


def test_named_theme_palettes_are_real_and_distinct():
    """Solarized/Gruvbox/Flexoki -- confirm each is actually a distinct
    palette (not accidentally aliased to light/dark or to each other)
    and that is_dark matches the palette's own name."""
    assert theme.THEMES["solarized_dark"]["is_dark"] is True
    assert theme.THEMES["solarized_light"]["is_dark"] is False
    assert theme.THEMES["gruvbox_dark"]["is_dark"] is True
    assert theme.THEMES["gruvbox_light"]["is_dark"] is False
    assert theme.THEMES["flexoki_dark"]["is_dark"] is True
    assert theme.THEMES["flexoki_light"]["is_dark"] is False

    all_bgs = [p["bg"] for p in theme.THEMES.values()]
    assert len(all_bgs) == len(set(all_bgs))  # every theme has a unique background
