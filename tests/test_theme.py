import theme


def test_palette_returns_dark_or_light():
    assert theme.palette(True) == theme.DARK
    assert theme.palette(False) == theme.LIGHT


def test_light_and_dark_have_the_same_keys():
    assert set(theme.LIGHT.keys()) == set(theme.DARK.keys())


def test_dark_and_light_backgrounds_are_actually_different():
    assert theme.LIGHT["bg"] != theme.DARK["bg"]
    assert theme.LIGHT["canvas_bg"] != theme.DARK["canvas_bg"]
