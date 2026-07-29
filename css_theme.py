"""Parse a real Obsidian-style CSS theme snippet (:root + .theme-light +
.theme-dark blocks of CSS custom properties) directly into Slate's own
palette dict shape, instead of hand-transcribing hex values into a
second Python data structure.

Real bug this exists to prevent, not a hypothetical one: mosscairn2.css
got live-edited mid-session while theme.py's _MOSSCAIRN3_LIGHT dict still
carried the values it was copied from hours earlier -- nobody noticed
until a live look caught it ("too tan"). The SAME class of drift then
recurred independently in webui/index.html, which had ALSO hand-copied
mosscairn2.css's old values into its own <style> block. Two unrelated
copies, same root cause: no mechanism keeps a hand-transcription in sync
with the file it was copied from. Parsing the real file at load time
removes the second copy entirely.

Scope, deliberately narrow: this handles exactly the property/value
patterns Runestone's own theme snippets actually use (confirmed by
reading mosscairn.css, boneink.css, inkbone.css) -- hex literals,
rgb(var(--name)) referencing a :root-declared R,G,B triple, and plain
var(--other-property) indirection one level through the same block. It
does NOT attempt to be a general CSS parser (no cascade, no specificity,
no media queries, no nested selectors) -- Obsidian snippets don't need
any of that for the properties Slate actually reads, and building a real
CSS engine for this would be the same mistake convert.py's own header
already named and rejected once (pymupdf4llm's hidden ML weight, pulled
in for a job a hand-rolled ~50-line function already did correctly).
Unrecognized formats fail loud (ValueError), matching how open_file
already fails loud on an HTML/image open with no working conversion --
a silently-wrong color is worse than a crash naming exactly what wasn't
understood.
"""
import re

# Slate palette key -> the CSS custom property it reads from. entry_bg
# and canvas_bg have no direct Obsidian equivalent (Slate invented that
# distinction for its own Entry/Canvas widgets) -- every real theme file
# checked so far sets both equal to the page background, so that's the
# default; button_bg similarly has no single canonical Obsidian name but
# --color-base-10 (the "one step toward fg" surface, --background-
# secondary's own usual value) is what every existing hand-port already
# used.
_PROPERTY_MAP = {
    "bg": "--color-base-00",
    "fg": "--text-normal",
    "button_bg": "--color-base-10",
    "muted_fg": "--text-muted",
    "select_bg": "--interactive-accent",
    "highlight_bg": "--interactive-accent",
}
# entry_bg/canvas_bg intentionally point at the same source as bg --
# handled as a post-step below, not through _PROPERTY_MAP, since they
# alias rather than read a distinct property.

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGB_VAR_RE = re.compile(r"^rgba?\(\s*var\(\s*(--[\w-]+)\s*\)\s*(?:,\s*[\d.]+\s*)?\)$")
_VAR_RE = re.compile(r"^var\(\s*(--[\w-]+)\s*\)$")
_HSL_RE = re.compile(r"^hsl\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)$")
_RGB_TRIPLE_RE = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$")


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _extract_block(text: str, selector: str) -> dict:
    """Grabs the FIRST `selector { ... }` block's custom-property
    declarations as {--name: raw-value-string}. Real files here only
    ever define each selector once with the properties Slate cares
    about; a later duplicate selector (rare, not seen in any real file
    checked) would just be ignored, not merged -- narrow scope on
    purpose, matching this module's own stated non-goals."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text)
    if not match:
        return {}
    body = match.group(1)
    props = {}
    for decl in body.split(";"):
        decl = decl.strip()
        if not decl or ":" not in decl:
            continue
        name, _, value = decl.partition(":")
        name = name.strip()
        if name.startswith("--"):
            props[name] = value.strip()
    return props


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l / 100.0, s / 100.0)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _resolve(raw: str, scope: dict, _depth: int = 0) -> str:
    """Resolves one property's raw CSS value to a #rrggbb hex string.
    `scope` is the merged {--name: raw-value} lookup (root vars +
    the current theme block's own declarations, block takes priority
    since a real file could redeclare a root var per-mode, though none
    checked so far do)."""
    if _depth > 5:
        raise ValueError(f"var() resolution too deep (possible cycle) resolving {raw!r}")
    raw = raw.strip()

    if _HEX_RE.match(raw):
        return raw.lower()

    m = _RGB_VAR_RE.match(raw)
    if m:
        triple = scope.get(m.group(1))
        if triple is None:
            raise ValueError(f"{raw!r} references undefined {m.group(1)!r}")
        rgb_m = _RGB_TRIPLE_RE.match(triple)
        if not rgb_m:
            raise ValueError(f"{m.group(1)!r} = {triple!r} is not an R,G,B triple")
        r, g, b = (int(x) for x in rgb_m.groups())
        return "#{:02x}{:02x}{:02x}".format(r, g, b)

    m = _VAR_RE.match(raw)
    if m:
        target = scope.get(m.group(1))
        if target is None:
            raise ValueError(f"{raw!r} references undefined {m.group(1)!r}")
        return _resolve(target, scope, _depth + 1)

    m = _HSL_RE.match(raw)
    if m:
        h, s, l = (float(x) for x in m.groups())
        return _hsl_to_hex(h, s, l)

    raise ValueError(
        f"unrecognized CSS color value {raw!r} -- css_theme.py only handles "
        "hex literals, rgb(var(--x)), var(--x), and hsl(h,s%,l%); "
        "extend the parser deliberately rather than guessing at this one"
    )


def _build_palette(root_vars: dict, block_vars: dict, is_dark: bool) -> dict:
    scope = {**root_vars, **block_vars}
    palette = {}
    for slate_key, css_var in _PROPERTY_MAP.items():
        raw = block_vars.get(css_var)
        if raw is None:
            raise ValueError(f"theme block is missing required property {css_var!r}")
        palette[slate_key] = _resolve(raw, scope)
    palette["entry_bg"] = palette["bg"]
    palette["canvas_bg"] = palette["bg"]
    palette["is_dark"] = is_dark
    return palette


def parse_obsidian_css(path: str) -> dict:
    """Returns {"light": {...Slate palette dict...}, "dark": {...}} for
    whichever of .theme-light/.theme-dark the file actually defines
    (Solarized-style single-mode files would return just one key --
    none of the files checked so far are single-mode, but nothing here
    assumes both exist)."""
    with open(path, "r", encoding="utf-8") as f:
        text = _strip_comments(f.read())

    root_vars = _extract_block(text, ":root")
    result = {}
    light_vars = _extract_block(text, ".theme-light")
    if light_vars:
        result["light"] = _build_palette(root_vars, light_vars, is_dark=False)
    dark_vars = _extract_block(text, ".theme-dark")
    if dark_vars:
        result["dark"] = _build_palette(root_vars, dark_vars, is_dark=True)
    return result
