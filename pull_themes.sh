#!/bin/sh
# Pulls a fresh copy of the palette JSONs from devs-themes
# (https://github.com/devinscodex/devs-themes, the central source of
# truth) into this project's own theme_data/ -- a plain copy, not a
# symlink, so Slate can keep tweaking its own copy independently
# without touching the central repo. Re-run this by hand whenever
# devs-themes changes and you want Slate to pick up the update.
# Assumes a sibling ../devs-themes checkout.
set -e
cd "$(dirname "$0")"
cp ../devs-themes/palettes/*.json theme_data/
echo "Pulled: $(ls theme_data/*.json | xargs -n1 basename | tr '\n' ' ')"
