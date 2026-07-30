"""Slate's version -- bumped manually on each notable release, not
computed from anything (fossil hash, build timestamp) that wouldn't
exist on a deployed end-user machine without fossil/git installed.
"Rolling" here means monotonic release markers, not auto-generated.
"""

AUTHOR = "devinscodex"

# AGPL-3.0-or-later (2026-07-29, Fable + Gilfoyle reviewed). Forced by
# PyMuPDF specifically, NOT Piper -- PyMuPDF is Slate's core rendering
# engine (used everywhere, not an optional feature) and its free tier is
# dual-licensed "GNU AFFERO GPL 3.0 or Artifex Commercial License"
# (confirmed live via `pip show pymupdf`, not assumed). Piper (TTS) is
# plain GPL-3.0-or-later, also bundled in-process -- GPLv3 SS13 and
# AGPLv3 SS13 have reciprocal FSF compatibility clauses letting a GPL-3.0
# component combine into an AGPL-3.0 work (not the reverse), so AGPL-3.0
# is the one license that cleanly covers the whole frozen Slate.exe
# rather than running a split-license codebase. Costs Devin nothing he
# wasn't already giving up (not reselling, no closed fork planned,
# already going public on GitHub) -- see LICENSE (full text) and the
# 2026-07-29 fossil commit message for the fuller reasoning, so a future
# "why not MIT?" question doesn't have to be re-derived from scratch.
LICENSE = "AGPL-3.0-or-later"

VERSION = "1.3.2"
# 1.0.0 -- v1 core: view, annotate, merge/split, redact, sign, forms, scan
# 1.1.0 -- gated text editing (all 4 slices: fontmatch, textedit, gate, UI)
# 1.2.0 -- theme roster overhaul (3 core families: Flexoki/Bonepaper/
#          Slate, defaulting to Slate Light), CSS-loadout parser
#          (css_theme.py) keeping theme.py in sync with its real Runestone
#          CSS source, Settings/About dialog polish (single-instance,
#          Escape-to-close, visible border, trimmed About copy), Fit
#          Width fixed for Book View's 2 columns, F12 now works from the
#          home screen. Devin, 2026-07-29: "there's been WAY more
#          iterations... that needs to be rolling with our changes" --
#          version bumps from here on track real shipped iterations, not
#          just headline features.
# 1.2.1 -- Fit Width now fits the CROPPED content width when crop_to_
#          content is on, not the full native page ("crop to content
#          doesn't seem to do anything" -- it worked, but Fit Width kept
#          re-measuring the uncropped page, so freed-up margin never
#          became extra zoom). Installer version now reads version.py
#          directly instead of a separately hardcoded string in
#          slate.iss (that drift is exactly what caused 1.2.0's
#          installer to briefly still say 1.1.0).
# 1.3.0 -- adjustable UI font size (Settings > UI Font Size, separate
#          from page Zoom) -- scales Tk's shared named fonts so nearly
#          every widget (menus, buttons, labels, tabs, dialogs, TOC)
#          grows/shrinks together, persisted like zoom/theme. Settings
#          dialog's checkboxes/radio buttons switched to indicatoron=
#          False (real toggle buttons, selectcolor fills the whole
#          button when checked) after Devin's live Slate Dark
#          screenshot showed the classic tiny indicator dot was hard to
#          tell selected from not.
# 1.3.1 -- Settings dialog reorganized (Devin, live screenshot review):
#          View collapsed from 6 loose rows into "Mode" (Continuous/
#          Book View, the 2 real reading modes -- View menu keeps all 3
#          real checkboxes unchanged) and "Display" (Colorize pages to
#          theme moved to the top, now also bound to F4 -- "colorize
#          pages is so hard to find sometimes and i toggle that one the
#          most"). Toggle-button colors now use each THEME's own accent
#          (select_bg) instead of one fixed universal green -- the
#          Theme grid shows each swatch's own real accent regardless of
#          which theme is active. Real bug fixed along the way: F8
#          (_kb_toggle_book_view) had lost its call to
#          _toggle_book_view() during this same edit, caught by the
#          existing regression test before it shipped.
# 1.3.2 -- License stamped: AGPL-3.0-or-later, real LICENSE file, About
#          page names it. Full 6-theme color audit (Devin: "check all
#          themes and color selections... make sure there's no
#          collisions") -- real WCAG contrast ratios computed, not
#          eyeballed: Bonepaper Light's checked-toggle text was 2.61:1
#          against its own accent (below the 3:1 UI floor) because the
#          TOC-selected-row convention this was modeled on (always use
#          colors["bg"] as checked-text) assumed bg beats fg for
#          contrast against the accent, true for 4 of 6 themes but false
#          for Slate Light and Bonepaper Light. Fixed generally --
#          _wire_toggle_button_contrast now picks whichever of bg/fg
#          wins real contrast per theme (_wcag_contrast_ratio), with a
#          regression test covering all 6 themes, not just the 2 that
#          broke. Also surfaced, not yet acted on: Flexoki's accent
#          (#4a7637/#62a945) sits close to Slate's own (#58763a/
#          #699d43, RGB distance ~17-21) -- both intentional green
#          accents for two different families, not a copy-paste
#          accident like the earlier Boneink/Inkbone collision, but
#          close enough to flag rather than silently leave.

SUMMARY = (
    "Slate is the document reader and editor you've always wanted: view, "
    "annotate, merge/split, fill forms, sign, redact, scan for sensitive "
    "content, and a gated mode for correcting body text -- no subscription, "
    "no login, no bloated installer. One reader for PDF, ebooks (EPUB/MOBI/"
    "FB2/CBZ), plain text, Markdown, HTML, images, and code. Built from "
    "proven libraries (PyMuPDF, pikepdf, pyHanko), not a reimplemented "
    "engine.\n\n"
    "Flexoki's light/dark modes are Steph Ango's (Kepano, Obsidian's CEO) "
    "open palette (stephango.com/flexoki) -- a nod to \"File Over App\" "
    "(stephango.com/file-over-app): data should outlive the software. "
    "Same reason Slate works on real files, not a project-specific "
    "format.\n\n"
    "Free and open-source under the GNU AGPL-3.0-or-later (see LICENSE). "
    "Coming to GitHub soon."
)
