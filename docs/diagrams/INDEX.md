# Slate documentation lineage (ANTInet: numeric-alpha, tree, index)

A revision never renumbers forward into a new slot -- it branches sideways off the
entry it corrects. `rev01`'s next real revision is `rev01a`, not `rev02`. `rev02` is
reserved for a genuinely NEW trunk topic, not a fix to rev01's content.

## Topic: Slate architecture + feature guide

- **rev01** (2026-10-29) -- first entry. Two companion docs, same source pass
  (direct read of trunk, SME subagent fan-out per module group):
  - `slate-architecture-rev01.html` -- module dependency map (Pele/Mermaid,
    dark theme, developer-facing). Hub-and-spoke: slate.py is the sole
    orchestrator; ~25 feature modules are leaves it imports and wires together.
  - `slate-feature-guide-rev01.html` -- plain-English (STE) feature guide,
    print-safe light theme, end-user facing. Verified against real print-to-PDF
    output, not just the screen render.

Both also delivered to `Desktop/Artifacts/` (Devin's standing default location).
