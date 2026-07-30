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

VERSION = "1.5.2"
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
# 1.3.3 -- Real bug caught live (Devin's Slate Dark screenshot):
#          Settings is a singleton dialog (built once, reused via
#          deiconify) -- selectcolor for Mode/Display/Voice/Speed was
#          only ever set at CONSTRUCTION time, under whatever theme was
#          active when the dialog first opened. Switching themes later
#          in that same still-open dialog repainted bg/fg everywhere,
#          but selectcolor (a separate Tk option _paint_widget never
#          touched) stayed frozen on the OLD theme's accent -- the
#          Voice group was stuck showing Bonepaper's jade while the
#          Theme grid's own "Dark" swatch correctly showed Slate's
#          green, an obvious mismatch. Fixed generally: the same
#          per-widget refresh callback _paint_widget already invokes on
#          every repaint now also reconfigures selectcolor for every
#          group except the Theme grid itself (whose swatches must stay
#          pinned to their OWN theme, never the active one).
# 1.4.0 -- Voice picker (Read Aloud menu + Settings) now offers only
#          the 2 bundled voices, no download required (Devin: "remove
#          the other 2 readback voices that need to be downloaded...
#          leave the 2 defaults there"). New Read Aloud > Sample
#          Voices... dialog lists ALL 4 voices with a Play button each,
#          playing bundled preview clips (tts.load_preview_audio) --
#          every voice stays sampleable without downloading anything.
#          Real gap caught before shipping: calling the real sounddevice
#          play() path directly (not through the existing background-
#          thread synthesis flow) genuinely HUNG in this no-audio-
#          device dev environment across repeated calls, not just
#          failed fast -- fixed with the same try/except-then-
#          "Playback failed" convention _read_current_page's own poll()
#          already uses, and the regression test mocks play() itself
#          rather than compounding known real-hardware flakiness.
# 1.4.1 -- Real bug caught live (Devin's screenshot): Settings/About's
#          own native OS titlebar never picked up dark mode at all --
#          _apply_native_titlebar_theme only ever targeted self.root.
#          Content colors were already correct (a separate, earlier-
#          fixed bug), which is exactly why this one was easy to miss.
#          Fixed generically via _paint_widget's own Toplevel branch
#          (reached automatically for every open dialog -- Settings,
#          About, Sample Voices, any future one -- not hand-listed).
#          Settings/About are now also modal (grab_set), always-on-top,
#          and transient to Slate's own main window (Devin: "should
#          both be modal and always on top... within Slate if
#          possible"). Standard's display label renamed once more.
#          "Flexoki" -> "Kepano" (Devin: "no need to mention Kepano
#          anymore as the theme name is now directly kepano") -- values
#          are still literally Flexoki's real published palette,
#          unchanged, only the label points straight at the person now.
# 1.5.0 -- Real regressions fixed: middle-click-drag pan (accidentally
#          commented out in an unrelated 2026-07-27 commit), About's
#          grab_set() blocking Settings underneath it when opened from
#          Settings' own button. Settings toggle-button contrast bump.
#          Theme grid's dark-on-dark unchecked-swatch bug fixed.
#          Bonepaper Light re-hued (kill a teal cast). "Kepano" label
#          reverted back to "Flexoki". New MEG theme family (light/
#          dark), real verified Martin Energy Group brand colors.
# 1.5.1 -- Same-session follow-up, real live feedback: Slate Light
#          re-hued to match Bonepaper's new olive green (Devin: "i like
#          that olive green more than the teal on slate light"). MEG
#          given real two-tone personality (bright primary for checked-
#          toggle fill, real secondary dark green for text-selection/
#          highlight) instead of one flat accent everywhere -- Devin:
#          "MEG is kinda pointless... add more spark/personality/
#          energy... green... more MEG."
# 1.5.2 -- Flexoki light/dark reverted to real stephango.com/flexoki
#          spec (Devin: "if flexoki dark could represent Kepano's
#          flexoki dark at home a lil better" / "flexoki light, can it
#          represent flexoki light a lil more at home?") -- Dark's bg/
#          button_bg back on real spec (base-950/base-900, undoing a
#          2026-07-25 deliberate lightening no longer needed now that
#          Inkbone is retired), both light+dark accents back to real
#          Flexoki blue instead of the shared house green. Bonepaper
#          Light re-derived via real numpy sampling over the boneink/
#          reference artwork (Devin: "a smidge more grundgier and
#          'bonier' and sepia, look to artwork for samples"). Settings/
#          About minimize with the main window now (Devin: "settings/
#          about still are 'children' windows as i believe they should
#          be if possible"). About/Settings/Sample Voices' fixed green
#          accent bar simplified to a single flag-driven declaration
#          (suckless pass) instead of paint-then-reassert in 3 places.

SUMMARY = (
    "Slate liberates all the editing.\n"
    "Slate liberates a trapped ecosystem.\n\n"
    "Slate is the PDF reader and editor you've always wanted: view, "
    "annotate, merge/split, fill forms, sign, redact, scan for sensitive "
    "content, and correct body text -- no subscription, no login, no "
    "bloat. Small and lightweight, with every creature comfort a real "
    "document workflow needs. One reader for PDF, ebooks (EPUB/MOBI/FB2/"
    "CBZ), plain text, Markdown, HTML, images, and code. Built on proven "
    "libraries (PyMuPDF, pikepdf, pyHanko), not a reimplemented engine.\n\n"
    "Free and open-source, forever, under the GNU AGPL-3.0-or-later. "
    "Why pay for Adobe or settle for Foxit when the real thing costs "
    "nothing?"
)
