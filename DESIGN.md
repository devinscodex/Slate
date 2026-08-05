# Slate — design

A small, no-bloat PDF editor, composed from proven libraries rather than a
reimplemented PDF engine. Full feature set: view, annotate/markup,
merge/split, redact, sign, form-fill, scan for sensitive content.

Built to be the document reader/editor we always wanted. Adobe is bloated
and predatory, Foxit is mediocre, Sumatra is nice but limited. Slate is
another free, open-source option, proof of how good FOSS can really be.

## Licensing posture (real, load-bearing constraint)

`pymupdf` is AGPL-3.0/commercial dual-licensed (Artifex) — confirmed
directly via its own package metadata, not assumed. Copyleft/source-
disclosure obligations trigger on **distribution outside your
organization** (or, AGPL-specifically, letting outside users interact
with a *modified* copy over a network as a service) — not on purely
private/internal use. Slate is a local desktop app, not a network
service, and isn't modifying PyMuPDF itself.

Slate is public on GitHub under AGPL-3.0-or-later (see LICENSE) --
this is not a legal ruling (get real legal review before relying on
this if it matters for a given deployment), and a look at Artifex's
commercial license (no public pricing -- requires contacting their
sales team directly) is the alternative if AGPL's source-disclosure
trigger is ever a problem for a specific use case.

## Why composition, not a new engine

Full ISO 32000 parity is a multi-year effort even for funded teams
(PDF.js/MuPDF/Poppler-scale). The right answer isn't reinventing that —
it's a thin app over libraries that already do each job well, matching this
project's own "wrap the real tool, don't reimplement" doctrine.

## Stack

- **GUI:** Tkinter (Python stdlib) — zero extra dependency for the toolkit
  itself.
- **Rendering / annotate / merge-split / forms:** PyMuPDF (`fitz`).
- **Redaction:** PyMuPDF's `apply_redactions()`, hardened (see below).
- **Redaction verification (independent second reader):** pikepdf
  (QPDF-backed — a different codebase than PyMuPDF/MuPDF, never let the
  same engine that wrote the file grade its own redaction).
- **Signing:** pyHanko (real PAdES B-B/B-T/B-LT/B-LTA, Acrobat-validation
  compatible — PyMuPDF's own signature-field support is basic/visual-only,
  not cryptographically real).
- **Encryption / password protection:** pikepdf.
- **Text-to-speech:** Piper (`tts.py`, `playback.py`) — see Read Aloud below.

## Redaction — the hardened save path (non-negotiable)

PyMuPDF's destructive-removal guarantee is conditional: physical removal
only holds "assuming `Document.save()` with a suitable garbage option."
`io_pdf.py`'s save path after any redaction must always:

- `garbage=4, clean=True` — never expose a faster save that skips this;
  skipping it leaves orphaned, recoverable objects in the file.
- `incremental=False` (full rewrite) — a PDF with prior incremental-update
  revisions keeps pre-redaction content byte-recoverable in its own
  revision history regardless of how clean the current revision is.
- Strip XMP/document metadata as part of the same hardened save — same
  underlying risk (content surviving in the wrong place) as the
  incremental-history issue, not a separate feature.

Real, sourced bugs exist in `apply_redactions()` (PyMuPDF GitHub #3433,
#2108, #3278 — over/under-redaction in certain content-stream layouts).
The test harness must catch both directions, not just "is it gone."

## Signing — sequencing constraint

PDF signatures are append-only-incremental by design: signing must be the
last write to a document. `io_pdf.py` must track signed-state and
warn-or-refuse further edits to an already-signed document rather than
silently invalidate the signature.

## Forms

**Radio sibling-unset** is handled by PyMuPDF itself: `Widget._checker()`
(verified against 1.28.0) auto-unsets every sibling in the same
field-name group on update. `forms.py` does nothing special;
`tests/test_forms.py::test_radio_sibling_auto_unset` pins this so a
future PyMuPDF upgrade that regresses it gets caught immediately.

**Radio GROUP creation** is NOT supported by PyMuPDF — adding two
`Widget()` objects with a shared `field_name` via `add_widget()` raises
`ValueError: bad xref` (matches PyMuPDF GitHub discussion #2333: only
filling an existing group's values is supported). Not a blocker --
Slate fills received forms, it doesn't author new ones -- but the test
fixture's radio group had to be built at the raw PDF-object level via
pikepdf instead.

**Widget page-lifetime:** a `Widget` holds only a *weak* reference to
its parent page; letting that page object go out of scope while still
holding widgets turns a later sibling-unset into a raw `ReferenceError`.
Always keep the page bound to a named variable for as long as any of
its widgets are being read or written.

## Build order (each slice has its own standalone pass/fail check)

Redaction is proven right after the minimum viewer needed to see
anything — early, not deferred to "once the UI feels done."

| # | Slice | Check |
|---|-------|-------|
| 0 | Skeleton: venv, fossil repo, Tkinter window opens a fixture PDF | Window opens, no exceptions, page count matches |
| 1 | Minimal viewer: render, nav, zoom | Every page of a fixture renders; checksums match expected |
| 2 | **Redaction core + verification harness (the trust gate)** | Plant a canary string + image in a fixture; redact; assert gone via PyMuPDF's `get_text()` AND a pikepdf raw-object scan (incl. orphaned objects) AND image byte-hash absent — on both a plain fixture and one with pre-existing incremental-update history — and explicitly assert the *unsafe* save path still shows the canary, proving the safe path is load-bearing |
| 3 | Merge/split/reorder/extract | Round-trip page count + per-page text-hash match |
| 4 | Annotate (highlight, freetext, ink, shapes, stamp) | Add one of each, reload, enumerate `page.annots()`, confirm type/rect/contents |
| 5 | Forms fill | One of each widget type; set, reload, confirm persisted; cross-check with an independent renderer; verify radio-sibling unsetting |
| 6 | Signing (pyHanko, PAdES B-B) | Sign with a self-signed test cert; verify via pyHanko's own independent validation call against the saved file |
| 7 | Security/encryption | Round-trip: correct password opens, wrong password fails, permission bits actually enforced |
| 8 | UI integration | One real end-to-end task per feature category, single sitting, no restarts |

## Scope decisions

**OUT of v1:** XFA (Adobe LiveCycle) forms (detect and warn, don't silently
mis-save). PDF/A validation/conversion (unless a real compliance need
surfaces — wrap veraPDF later, don't hand-roll). OCR for scanned PDFs
(image-region redaction still works without it).

**IN v1:** opening and producing password-protected PDFs. A mandatory
safe-save policy — never overwrite the original in place; auto-backup or
save-as-copy before any destructive op, especially redaction.

**Business question, not engineering:** PAdES B-LT/B-LTA needs a real
non-self-signed cert to matter to external recipients — v1 ships B-B
(fine for internal sign-off), B-LT/LTA only worth building once a real
signing cert exists.

## Scan for sensitive content (`scan.py`)

**Scope:** number-shaped financial/PII patterns only — SSN
(`123-45-6789`), ABA routing numbers, labeled account numbers, and
Luhn-valid credit card numbers. Does NOT catch general PII (a resume's
phone/address with no account-shaped context), business-confidential
content, or anything on an image-only/scanned page — same OCR gap
already named out-of-v1 for redaction itself. A page with 0 extractable
characters is reported as its own `unscannable` finding rather than
silently folded into "nothing found" — those are different claims.

**Gotcha:** real PDFs routinely put a label and its value on different
lines (e.g. `Account Number:`, a blank line, then the digits, as three
separate lines) -- a same-line regex (`Account Number:\s*(\d+)`)
silently reports these files clean. Fixed by scanning forward a few
non-blank lines after a label match; pinned by
`test_label_and_value_on_separate_lines_regression`.

**UI wiring:** Edit → "Scan this document..." runs `scan.scan_document`
against the open file and offers to mark every hit with a resolvable
rect as a pending redaction in one click — scan and redact are meant to
chain together, not be two disconnected features. File → "Scan folder
for sensitive PDFs..." reuses `scan.scan_directory` for the batch-audit
case.

## Text editing — gated feature

Editing existing body-paragraph text sits behind a passphrase gate,
off by default -- a deliberate scope call: the rest of v1 stays open
to everyone, but text editing doesn't ship enabled by default on a
document meant to stay in its "final form" for most users.

Editing existing PDF body text means re-flowing text runs and matching
the original font/kerning exactly — PDF is page-fixed glyph positions,
not a reflow format. Even Adobe/Foxit's own "Edit Text" is imperfect at
this. Approach: redact-then-reinsert (`add_redact_annot` +
`apply_redactions()` + `insert_text` at the same spot) — **with the
redaction fill set to white/transparent, not black** (`fill=(1, 1, 1)`,
not `redact.py`'s `mark_region()`, which is correctly black-fill for
actual redaction).

**Three-tier font-safety approach:** before falling to a crude Base-14
substitute, check whether the same font is already installed as a real
system font first — most business PDFs use Calibri/Arial/Times New
Roman/Segoe UI, already sitting on the same Office-standardized
Windows machines that would run Slate.
1. **reusable** — font fully embedded, not subsetted (`page.get_fonts()`,
   no `ABCDEF+` prefix) → reuse via `extract_font`/`insert_font`.
2. **system-font** — `fontmatch.find_system_font()`: Windows via stdlib
   `winreg` checking HKCU then HKLM with name normalization, verified
   via `fitz.Font(fontfile=...).name`; Linux via `fc-match` for dev,
   with a real pitfall: `fc-match` never fails, it always substitutes
   a "closest" font (`fc-match "Calibri"` on a box with no Calibri
   silently returns `DejaVu Sans`) -- must compare the *returned*
   family against what was asked for, reject a mismatch as "not really
   installed."
3. **substitute-needed** — Base-14 mapped from the font's flags bitfield
   (serif/bold/italic/monospace). Only this tier needs an up-front
   warning in the UI — 1 and 2 are both real fonts.

Verified against a genuinely embedded, non-subsetted font
(`ext='ttf'`, `basefont='DejaVu Serif Book'`, no subset prefix): tier 1
renders visually identical to the original; tier 2 renders a real
typeface with correct glyph shapes; tier 3 renders but with visibly
different letterforms (serif style, spacing, descenders) -- confirming
the predicted degradation is real, not alarmist.

**Gate mechanism:** `hashlib.pbkdf2_hmac("sha256", ..., 600_000)`, local
salted hash (not plaintext) at `~/.slate/unlock.json` (same convention
as `recent.py`), stdlib-only. First-run: clicking "Edit Text" with none
set yet prompts to set one right there, no separate admin step. Unlock
is session-only, re-locks on restart. Stated plainly: a local UX gate,
not real access control.

Two real bugs caught building this:
- `font_safety`'s match compared `page.get_fonts()`'s `name` field
  (the page's font-*resource* alias, e.g. `"F1"`) against `span["font"]`
  (the font's own internal name, e.g. `"DejaVuSerif"`) -- different
  strings even for a font this exact code just embedded itself. This
  would have made tier 1 (reuse) silently never fire on *any* real
  document. Fixed: compare `span["font"]` against `basefont` (the
  font's real reported name, subset-prefix stripped), normalized with
  `fontmatch`'s existing `_normalize_font_name` (already built,
  already tested).
- `edit_text` called `page.insert_font()` for the reusable/system-font
  tiers *before* `apply_redactions()`. `apply_redactions()` rebuilds
  page resources and drops any font not yet referenced by the content
  stream -- so the just-registered font vanished before `insert_text`
  could use it. Fixed by moving font registration to *after* the
  redaction call, immediately before the actual `insert_text`.

## Live theme color editor (`theme.py`, `slate.py` — added 2026-08-03)

Settings → Theme → "Edit Colors..." opens a real, non-modal editor for
the 12 authored base keys (`bg`, `fg`, `button_bg`, `entry_bg`,
`canvas_bg`, `select_bg`, `muted_fg`, `highlight_bg`, `faint_fg`,
`bg2`, `bg3`, `border`) of whichever theme is currently active.
Deliberately not modal (no `grab_set`) — the main window stays fully
interactable so a color can be judged against a real open document, not
just the dialog's own preview chips.

**Live-apply mechanism**: `theme.update_live()` mutates `THEMES[name]`
in place and recomputes the chrome cascade; the editor then calls the
same `_on_theme_changed()` path a normal theme switch already uses — no
separate "preview" palette, the running app's real theme data changes
under it. `theme.save_family_values()` writes the 12 keys back to
`devs-themes/palettes/<family>.json` (the real cross-app source of
truth also consumed by webUI/Runestone) AND Slate's own pulled
`theme_data/<family>.json` copy in one action, with an optional
`sync_all.py` call to also patch webUI/Runestone. `reload_from_disk()`
discards live edits back to last-saved.

**Color picker**: a real HSL wheel (hue, drag around the ring) +
saturation/lightness box (recolored live per the current hue), both
rendered via PIL-generated gradient images rather than Tk's native OS
color dialog — Devin's explicit ask, "HSL is truly the language of
colors." The wheel image is computed once and cached at class level
(pure hue, no S/L dependence); the box regenerates only on hue change,
not on every S/L drag.

**Real perf gotcha, found in review (Gilfoyle) and fixed same session**:
`_on_theme_changed()` does a full app repaint AND, if a document is
open, a full page-cache invalidate + re-render — "same cost as a zoom
change" by its own existing docstring. `B1-Motion` fires far faster
than a page can re-render, and the picker's whole point is judging a
color against a real open page — a real render-storm on every drag
tick. Fixed with a debounce (60ms coalesce on the expensive path,
immediate flush on `<ButtonRelease-1>` so the released value is never
left stale) — the picker's own local visual feedback (cursor position,
preview swatch, hex/rgb/hsl readout) stays fully synchronous regardless,
only the app-wide propagation is throttled.

## Fixtures

`tests/fixtures/` holds small synthetic PDFs only — generated
programmatically, never real documents. One fixture must include
pre-existing incremental-update history (to catch the redaction/history
gap above) and one must include a pre-existing tag tree (to confirm
redact/merge/annotate don't silently strip it, even though authoring
tagged PDF is out of v1). Same discipline applies to the synthetic epub
fixture used below — built at test time via `zipfile`, never committed
as a binary.

Exception: `basic3page.pdf` itself IS committed as a small (1.5KB)
static binary rather than generated at test time. It still satisfies
the actual intent ("never a real document" -- it's fully synthetic, 3
pages of `insert_text`); converting it to generate-at-test-time would
mean rewiring ~30 call sites in `test_integration.py` for a purely
cosmetic gain.

## Sumatra-parity backlog

SumatraPDF's TOC/recent-files panel is this project's own UX reference;
three concrete slices peeled from it:

1. **`search.py` + keyboard nav** — in-document Find (`/` or View >
   Find...), `Return`/`Shift-Return`/`n`/`N` step through matches with
   wraparound, current match highlighted red vs. yellow for the rest
   (canvas overlay, redrawn every `render()`, not real annotations).
   `j`/`k` page nav, `g`/`G` jump to first/last page. Reuses PyMuPDF's
   own `page.search_for()` (already case-insensitive). Gotcha:
   `search_for("")` returns `None`, not `[]` — guarded explicitly. All
   single-letter bindings are guarded on "is an Entry currently
   focused" so they don't hijack literal search text.
2. **Tabs** — `tab.py`'s `Tab` is a plain per-document state container
   (path/doc/viewer/page/mode/pending_redactions/search_state).
   `ttk.Notebook` is used purely as a tab-*selector strip* — each "tab"
   is a never-shown placeholder child frame; the single existing
   shared toolbar/canvas/find-bar/toc keeps doing all the actual
   rendering, unchanged. On switch, the outgoing tab's mutable fields
   save back into its `Tab`, the incoming tab's fields load into the
   same flat `self.doc`/`self.path`/etc. attributes every pre-existing
   method already reads. Gotcha: selecting a `Notebook` tab only fires
   `<<NotebookTabChanged>>` on the next idle-loop pass, not
   synchronously -- fixed via a `_select_tab()` helper that calls the
   handler directly.
3. **Ebook formats** (EPUB/MOBI/FB2/CBZ/TXT/MD) — PyMuPDF/MuPDF already
   opens all of these natively (confirmed via its own docs feature
   matrix and hands-on with a real synthetic epub). Zero new
   dependency, mostly widening `open_file()`'s dialog filter. CHM is
   *not* supported (would need PyMuPDF Pro) — left out. PDF-only
   Edit/File menu items are disabled whenever the active tab's document
   isn't a real PDF (`doc.is_pdf`), via `_update_pdf_only_menu_state()`
   hooked into the tab-switch path. Gotcha: `_title()` unconditionally
   ran `sign.is_signed()` (pyHanko) against `self.path`, which crashed
   with "Illegal PDF header" the instant a non-PDF path was opened --
   fixed by gating that check on `doc.is_pdf` too.

**Explicitly still out of scope:** adjustable reflow for epub (font
size is covered by the global UI Font Size setting, but true reflow
isn't). TTS and night mode are no longer out of scope -- see Read
Aloud below and the multi-theme roster (Slate/Bonepaper/Flexoki/Martin,
each with a dark variant).

## Convert — office document utilities (`convert.py`)

New "Convert" menu: PDF -> Markdown, PDF -> plain text, PDF -> page images
(PNG, chosen DPI), and images -> PDF. All read-only exports work on any
open document type (PDF or ebook), same as Scan. Zero new dependencies:
everything reuses PyMuPDF.

`pymupdf4llm` looked like the obvious off-the-shelf PDF->Markdown
choice, but actually installing it pulls `pymupdf-layout` (a 41MB
wheel) plus a full ONNX Runtime, numpy, protobuf, networkx — 80MB+ of
transitive weight for a layout-detection ML model. `pdf_to_markdown`
is hand-rolled instead, reusing the same span-level size/flags data
`textedit.py` already parses for font info: heading level is inferred
from font size *relative to the document's own body-text size* (not a
fixed threshold), whole-line-bold text becomes `**bold**`,
bullet-prefixed lines normalize to real `- ` markdown list items.

Gotcha: the body-size heuristic originally picked the size with the
most *lines*, which ties when a one-line title and a one-line body
have equal line counts. Fixed by weighting by total *character volume*
instead -- a much more reliable "which size is actually the body text"
signal.

`images_to_pdf` uses PyMuPDF's own documented technique
(`Document.convert_to_pdf()` per image), one full page per image, in
the given order.

**Explicitly out of scope, flagged for later:** DOCX/XLSX <-> PDF
conversion. Genuinely useful, but the only real options are
heavy/platform-specific (headless LibreOffice as an external process
dependency, or MS Office COM automation via `pywin32` — Windows-only,
needs Word/Excel installed). Needs its own research pass, not a quick
add.

## Read Aloud — text-to-speech (`tts.py`, `playback.py`)

**Current shipped state (2026-08-03): fully excluded from the build.**
`Slate.spec`'s `excludes=['piper', 'onnxruntime', 'sounddevice',
'soundfile']` — real ~35MB removed (onnxruntime alone is 34.55MB) and,
separately, a real Windows-Defender false-positive trojan flag on the
shipped binary (UPX packing was the other, larger half of that fix —
see Build/binary trust below). `tts.ENGINE_AVAILABLE` gates every UI
call site; the feature is simply absent, not hidden-but-present. The
rest of this section documents the real, working design underneath —
still true architecturally, just not currently shipped. Real next step,
not yet built: download-on-demand for the engine itself (not just
voices, which already work this way below) — a frozen PyInstaller exe
can't `pip install` into itself at runtime, so this needs either a
separate self-contained piper build invoked as a subprocess, or a
side-by-side embedded Python; a real design pass, not a quick add.

A ~250MB size budget for "quality (limited), voices of choice" is
workable. Piper TTS: engine is GPL-3.0-or-later, voices are
MIT-licensed, both confirmed via HuggingFace's own package/model
metadata. Zero-cost, FOSS, own-forever.

**Voice selection was a real listening test, not a guess** — 3 rounds:
a plain sentence across 25 real named voices (multi-speaker corpora
like arctic/libritts/vctk excluded -- those bundle dozens of speakers
per model, not a single named voice); a numbers/punctuation/date/
currency stress-test passage sorted into `like`/`no-like` piles (found
a non-obvious pattern: quality tier wasn't the deciding factor at all,
British-accented voices had a much higher like-rate (4/5) than
American ones (3/9) in this set, and a "robotic"/"choppy" character
explained most rejects); and a public-domain narrative passage
(opening of *Pride and Prejudice*) across the finalists, to test
sustained reading.

Final four: **northern_english_male** (GB male, medium, 22kHz -- the
bundled default), **alba** (GB female, medium, 22kHz),
**southern_english_female** (GB female, low, 16kHz), **danny** (US
male, low, 16kHz). The two low-tier voices both hit a "missing phoneme
from id map" warning on the harder stress-test passage (a stress-mark
symbol) -- not disqualifying, but a real quality wrinkle those two
specifically carry.

**Distribution:** only `northern_english_male` ships bundled in the
repo (`voices/`) as the zero-setup default. The other three download
on first use into `~/.slate/tts-voices/` (same config convention as
`recent.py`/`gate.py`/`theme.py`) rather than permanently carrying
every voice's weight in the installer. Small preview clips for all
four (`voices/previews/`) ship bundled so a voice can be sampled
before committing to its full download.

**Playback:** Piper only *synthesizes* audio, it doesn't play it.
`sounddevice`+`soundfile` add almost no new weight (numpy is already
required by `onnxruntime`, which `piper-tts` itself needs).
`sounddevice` has no built-in pause/resume (only start/stop of a
stream) -- `playback.py`'s `Player` implements real pause (holds
position, resumes from exactly there) via a streaming callback
tracking position + a paused flag directly.

**Speed control** reuses Piper's own real `length_scale` synthesis
parameter rather than needing separate audio time-stretching -- the
UI's speed multiplier maps to `length_scale = 1 / speed`.

**Thread-safety gotcha:** the download progress callback originally
called `self.root.after(...)` directly from the background download
thread -- Tkinter is not thread-safe, raising `main thread is not in
main loop` the first time a real download ran through the UI (not
caught by `tts.py`'s own unit tests, which mock the network and never
exercise real threading). Fixed by having the worker thread only ever
write to a plain shared dict; `poll()` -- scheduled via
`self.root.after()`, always on the main thread -- is the only thing
that touches real widgets.

**Not verified against real audio hardware:** this dev environment
(WSL2) exposes zero audio output devices even with `libportaudio2`
installed -- a WSL passthrough gap, not a defect in this code. The
real Windows deployment has no such issue (`sounddevice`'s wheel
bundles PortAudio with normal native device access). The playback
callback's own position/pause logic is still fully tested by calling
it directly with synthetic buffers. `do_read_page()`'s synthesis path
is fully exercised end-to-end against the actual bundled model; only
the final "make sound come out of speakers" step is untestable here.
