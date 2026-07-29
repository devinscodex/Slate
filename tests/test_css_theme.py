"""css_theme.py: the Obsidian-CSS-to-Slate-palette parser. Unit tests
here use small inline CSS snippets (no dependency on Runestone existing
on disk, so these always run everywhere Slate's own suite runs); the
live-file consistency check at the bottom is skipped when Runestone
isn't present -- it exists to catch a hand-tuned theme.py dict drifting
from its real CSS source, the exact bug this whole module exists to
prevent (see theme.py's own _MOSSCAIRN_DARK comment for the real
instance this caught, 2026-07-29).
"""
import os
import tempfile

import pytest

import css_theme
import theme

_RUNESTONE_SNIPPETS = "/mnt/c/bin/projects/runestone/.obsidian/snippets"


def _write(tmp_path, content):
    path = str(tmp_path / "sample.css")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_parses_hex_literals_and_var_indirection(tmp_path):
    css = """
    .theme-light {
      --color-base-00: #eeeeee;
      --text-normal: #111111;
      --color-base-10: #dddddd;
      --text-muted: #333333;
      --interactive-accent: #4a7637;
    }
    """
    path = _write(tmp_path, css)
    result = css_theme.parse_obsidian_css(path)
    assert result["light"] == {
        "bg": "#eeeeee", "fg": "#111111", "button_bg": "#dddddd",
        "muted_fg": "#333333", "select_bg": "#4a7637", "highlight_bg": "#4a7637",
        "entry_bg": "#eeeeee", "canvas_bg": "#eeeeee", "is_dark": False,
    }
    assert "dark" not in result  # file only defines .theme-light


def test_resolves_rgb_var_root_reference(tmp_path):
    css = """
    :root { --moss: 74, 118, 55; }
    .theme-dark {
      --color-base-00: #000000;
      --text-normal: #ffffff;
      --color-base-10: #111111;
      --text-muted: #222222;
      --interactive-accent: rgb(var(--moss));
    }
    """
    path = _write(tmp_path, css)
    result = css_theme.parse_obsidian_css(path)
    assert result["dark"]["select_bg"] == "#4a7637"
    assert result["dark"]["is_dark"] is True


def test_resolves_var_indirection_one_level(tmp_path):
    css = """
    .theme-light {
      --color-base-00: #abcdef;
      --background-primary: var(--color-base-00);
      --text-normal: #010101;
      --color-base-10: #dddddd;
      --text-muted: #222222;
      --interactive-accent: #4a7637;
    }
    """
    path = _write(tmp_path, css)
    result = css_theme.parse_obsidian_css(path)
    # --color-base-00 is read directly (bg's real mapping), but this
    # proves plain var() indirection resolves correctly in general --
    # exercised here via a property this parser doesn't itself read,
    # confirming _resolve()'s var() branch works independent of which
    # Slate key happens to use it.
    resolved = css_theme._resolve("var(--background-primary)", {
        **css_theme._extract_block(css_theme._strip_comments(css), ":root"),
        **css_theme._extract_block(css_theme._strip_comments(css), ".theme-light"),
    })
    assert resolved == "#abcdef"


def test_resolves_hsl(tmp_path):
    assert css_theme._resolve("hsl(0, 0%, 0%)", {}) == "#000000"
    assert css_theme._resolve("hsl(0, 0%, 100%)", {}) == "#ffffff"


def test_unrecognized_format_fails_loud():
    with pytest.raises(ValueError, match="unrecognized CSS color value"):
        css_theme._resolve("oklch(0.5 0.1 180)", {})


def test_undefined_var_reference_fails_loud():
    with pytest.raises(ValueError, match="undefined"):
        css_theme._resolve("var(--does-not-exist)", {})


def test_missing_required_property_fails_loud(tmp_path):
    css = ".theme-light { --color-base-00: #eeeeee; }"  # missing --text-normal etc.
    path = _write(tmp_path, css)
    with pytest.raises(ValueError, match="missing required property"):
        css_theme.parse_obsidian_css(path)


def test_comments_are_stripped_before_parsing(tmp_path):
    css = """
    /* --interactive-accent: #ff0000; -- a decoy inside a comment */
    .theme-light {
      --color-base-00: #eeeeee;
      --text-normal: #111111;
      --color-base-10: #dddddd;
      --text-muted: #333333;
      --interactive-accent: #4a7637; /* the real one */
    }
    """
    path = _write(tmp_path, css)
    result = css_theme.parse_obsidian_css(path)
    assert result["light"]["select_bg"] == "#4a7637"


@pytest.mark.skipif(
    not os.path.isdir(_RUNESTONE_SNIPPETS),
    reason="Runestone vault not present on this machine -- dev-only consistency check",
)
@pytest.mark.parametrize("filename,dark_key,light_key", [
    ("boneink.css", "boneink_dark", "boneink_light"),
    ("mosscairn.css", "mosscairn_dark", "mosscairn_light"),
])
def test_shipped_theme_dicts_match_the_real_current_css_file(filename, dark_key, light_key):
    """The real point of this whole module: theme.py's hand-tuned dicts
    must not silently drift from the CSS files they were copied from.
    This is the automated version of the manual check that caught
    _MOSSCAIRN_DARK's muted_fg mistake (2026-07-29) -- runs every time
    the suite runs on a machine with Runestone present, so the next
    drift gets caught by CI/local test runs instead of a live look."""
    path = os.path.join(_RUNESTONE_SNIPPETS, filename)
    parsed = css_theme.parse_obsidian_css(path)
    shipped_dark = theme.THEMES[dark_key]
    shipped_light = theme.THEMES[light_key]
    # entry_bg has no real CSS property to read (Slate invented that
    # distinction for its own Entry widgets) -- css_theme.py defaults it
    # to bg, but Solarized-derived families (Mosscairn Dark included)
    # deliberately give it button_bg's tone instead, a real pre-existing
    # per-family choice, not drift. Excluded from this check on purpose,
    # not silently -- everything else the CSS file CAN define still
    # gets checked. Same for chrome-cascade keys (menubar_bg etc.),
    # which _with_chrome_cascade() computes, never sourced from the CSS.
    skip_keys = {"entry_bg"}
    for key in parsed["dark"]:
        if key in skip_keys:
            continue
        assert parsed["dark"][key] == shipped_dark[key], (
            f"{dark_key}.{key}: CSS file says {parsed['dark'][key]!r}, "
            f"theme.py says {shipped_dark[key]!r} -- drifted"
        )
    for key in parsed["light"]:
        if key in skip_keys:
            continue
        assert parsed["light"][key] == shipped_light[key], (
            f"{light_key}.{key}: CSS file says {parsed['light'][key]!r}, "
            f"theme.py says {shipped_light[key]!r} -- drifted"
        )
