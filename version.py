"""Slate's version -- bumped manually on each notable release, not
computed from anything (fossil hash, build timestamp) that wouldn't
exist on a deployed end-user machine without fossil/git installed.
"Rolling" here means monotonic release markers, not auto-generated.
"""

AUTHOR = "devinscodex"

# AGPL-3.0-or-later. Forced by PyMuPDF, not Piper: PyMuPDF's free tier is
# dual-licensed "GNU AFFERO GPL 3.0 or Artifex Commercial License"
# (verified via `pip show pymupdf`). Piper (TTS) is plain GPL-3.0-or-
# later. GPLv3 SS13 and AGPLv3 SS13 have reciprocal FSF compatibility
# clauses letting a GPL-3.0 component combine into an AGPL-3.0 work (not
# the reverse), so AGPL-3.0 covers the whole frozen Slate.exe rather than
# a split-license codebase. See LICENSE for full text.
LICENSE = "AGPL-3.0-or-later"

VERSION = "1.5.4"
# 1.0.0 -- core: view, annotate, merge/split, redact, sign, forms, scan
# 1.1.0 -- gated text editing (fontmatch, textedit, gate, UI)
# 1.2.0 -- theme roster overhaul (Flexoki/Bonepaper/Slate, default Slate
#          Light), CSS-loadout parser (css_theme.py) keeps theme.py in
#          sync with its Runestone CSS source, Settings/About dialog
#          polish (single-instance, Escape-to-close, visible border,
#          trimmed About copy), Fit Width fixed for Book View's 2
#          columns, F12 works from the home screen.
# 1.2.1 -- Fit Width fits the CROPPED content width when crop_to_content
#          is on, not the full native page. Installer version reads
#          version.py directly instead of a separately hardcoded string
#          in slate.iss.
# 1.3.0 -- adjustable UI font size (Settings > UI Font Size, separate
#          from page Zoom) -- scales Tk's shared named fonts so every
#          widget grows/shrinks together, persisted like zoom/theme.
#          Settings checkboxes/radio buttons switched to indicatoron=
#          False (real toggle buttons).
# 1.3.1 -- Settings dialog reorganized: View collapsed into "Mode"
#          (Continuous/Book View) and "Display" (Colorize pages to theme
#          moved to top, bound to F4). Toggle-button colors use each
#          theme's own accent (select_bg) instead of one fixed color.
#          Fixed: F8 (_kb_toggle_book_view) had lost its call to
#          _toggle_book_view().
# 1.3.2 -- License stamped: AGPL-3.0-or-later, LICENSE file, About page
#          names it. Full theme color audit -- real WCAG contrast
#          ratios computed: Bonepaper Light's checked-toggle text was
#          2.61:1 against its own accent (below the 3:1 floor).
#          _wire_toggle_button_contrast now picks whichever of bg/fg
#          wins real contrast per theme, regression test covers all 6
#          themes.
# 1.3.3 -- Fixed: Settings is a singleton dialog (built once, reused via
#          deiconify) -- selectcolor for Mode/Display/Voice/Speed was
#          only set at construction time, so switching themes in an
#          already-open dialog left selectcolor frozen on the old
#          theme's accent. _paint_widget's repaint now also reconfigures
#          selectcolor on every repaint, except the Theme grid itself.
# 1.4.0 -- Voice picker (Read Aloud menu + Settings) offers only the 2
#          bundled voices, no download required. New Read Aloud >
#          Sample Voices... dialog lists all 4 voices with a Play
#          button each, playing bundled preview clips. Fixed: calling
#          the sounddevice play() path directly (bypassing the
#          background-thread synthesis flow) hung across repeated
#          calls in a no-audio-device environment.
# 1.4.1 -- Fixed: Settings/About's native OS titlebar never picked up
#          dark mode -- _apply_native_titlebar_theme only ever targeted
#          self.root. Fixed generically via _paint_widget's Toplevel
#          branch (reaches every open dialog automatically). Settings/
#          About are modal (grab_set), always-on-top, transient to the
#          main window. "Flexoki" label renamed to "Kepano" (values
#          unchanged).
# 1.5.0 -- Fixed regressions: middle-click-drag pan (accidentally
#          commented out in an earlier commit), About's grab_set()
#          blocking Settings when opened from Settings' own button.
#          Settings toggle-button contrast bump. Theme grid's
#          dark-on-dark unchecked-swatch bug fixed. Bonepaper Light
#          re-hued. "Kepano" label reverted to "Flexoki". New MEG theme
#          family (light/dark), verified Martin Energy Group brand
#          colors.
# 1.5.1 -- Slate Light re-hued to match Bonepaper's olive green. MEG
#          given two-tone accent (bright primary for checked-toggle
#          fill, darker secondary for text-selection/highlight) instead
#          of one flat accent everywhere.
# 1.5.2 -- Flexoki light/dark reverted to real stephango.com/flexoki
#          spec -- dark's bg/button_bg back on spec (base-950/base-900),
#          both light+dark accents back to real Flexoki blue instead of
#          the shared house green. Bonepaper Light re-derived via numpy
#          sampling over reference artwork. Settings/About minimize with
#          the main window. Fixed green accent bar simplified to a
#          single flag-driven declaration.
# 1.5.3 -- Theme picker rebuilt: ttk.Combobox for family + 2 plain
#          tk.Radiobutton widgets for Light/Dark, both native controls
#          with their own selected-state. 3-chip palette preview
#          (bg/button_bg/select_bg). Active tabs get a subtle accent
#          tint (active_tab_bg, 35% toward select_bg from button_bg).
#          Bonepaper Dark's button_bg synced to match the webUI value.
# 1.5.4 -- Only northern_english_male ships bundled now (alba moved to
#          download-on-first-use, same as the other 2 optional voices)
#          -- installer/tarball ~60MB smaller. Removed unused icon-
#          concept draft files from branding/. New Settings > Display
#          checkbox: "Check for updates on start" (default on).
#          DESIGN.md trimmed (build-log/slice-tracking narration cut,
#          technical content kept).

SUMMARY = (
    "Slate liberates all the editing.\n"
    "Slate liberates a trapped ecosystem.\n\n"
    "View, annotate, merge/split, redact, sign, fill forms, correct text. "
    "Reads PDF, ebooks, text, Markdown, HTML, images, and code -- one "
    "lightweight tool, not ten apps for ten formats. Built on proven "
    "libraries (PyMuPDF, pikepdf, pyHanko), not reinvented.\n\n"
    "Free and open-source, forever, under the GNU AGPL-3.0-or-later -- "
    "because software should serve the file, not the company selling it. "
    "Why pay for Adobe?"
)
