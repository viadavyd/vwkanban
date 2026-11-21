#!/usr/bin/env sh
# pre-commit hook: run the frontend's pinned prettier (and its svelte plugin) from frontend/.
set -eu
cd frontend
for f in "$@"; do
  set -- "$@" "${f#frontend/}"
  shift
done
exec node_modules/.bin/prettier --write --ignore-unknown "$@"
