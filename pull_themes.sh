#!/bin/sh
# Pulls a fresh copy of the palette JSONs from themes-custom (the central
# source of truth, see /mnt/c/bin/projects/themes-custom/README.md) into
# this project's own theme_data/ -- a plain copy, not a symlink, so Slate
# can keep tweaking its own copy independently without touching the
# central repo. Re-run this by hand whenever themes-custom changes and you
# want Slate to pick up the update.
set -e
cd "$(dirname "$0")"
cp ../themes-custom/palettes/*.json theme_data/
echo "Pulled: $(ls theme_data/*.json | xargs -n1 basename | tr '\n' ' ')"
