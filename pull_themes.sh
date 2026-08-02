#!/bin/sh
# Pulls a fresh copy of the palette JSONs from devs-themes (the central
# source of truth, see /mnt/c/bin/projects/devs-themes/README.md,
# renamed from themes-custom 2026-08-02) into this project's own
# theme_data/ -- a plain copy, not a symlink, so Slate can keep tweaking
# its own copy independently without touching the central repo. Re-run
# this by hand whenever devs-themes changes and you want Slate to pick
# up the update.
set -e
cd "$(dirname "$0")"
cp ../devs-themes/palettes/*.json theme_data/
echo "Pulled: $(ls theme_data/*.json | xargs -n1 basename | tr '\n' ' ')"
