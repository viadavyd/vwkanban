#!/usr/bin/env bash
# The fast local gate: lint, types and unit/API/WS tests, with quiet output (only
# failures and a one-line summary per step), so a Claude session reads little.
#
#   scripts/check.sh            everything
#   scripts/check.sh backend    backend only (extra args go to pytest, e.g. -k csv)
#   scripts/check.sh frontend   frontend only
#
# Browser e2e against the running stack is scripts/e2e.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
what=${1:-all}
[ $# -gt 0 ] && shift
fail=0

step() { # name, command...
  local name=$1; shift
  local out
  if out=$("$@" 2>&1); then
    echo "ok   $name: $(printf '%s\n' "$out" | grep -E 'passed|Tests |COMPLETED|All checks' | tail -1)"
  else
    fail=1
    echo "FAIL $name"
    printf '%s\n' "$out" | tail -40
  fi
}

if [ "$what" = all ] || [ "$what" = backend ]; then
  scripts/dev-db.sh >/dev/null
  step ruff bash -c 'cd backend && uv run ruff check . && uv run ruff format --check .'
  step pytest bash -c 'cd backend && uv run pytest -q -p no:cacheprovider "$@"' _ "$@"
fi
if [ "$what" = all ] || [ "$what" = frontend ]; then
  step svelte-check bash -c 'cd frontend && npm run check --silent'
  step prettier bash -c 'cd frontend && npx prettier --check . --log-level warn'
  step vitest bash -c 'cd frontend && npm test --silent'
fi
exit $fail
