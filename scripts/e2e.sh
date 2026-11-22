#!/usr/bin/env bash
# Browser e2e (frontend/e2e/app) against the local stack at PUBLIC_URL, reading the
# logins from .env (ADMIN_USERNAME, ADMIN_PASSWORD, BOB_PASSWORD). Quiet: prints failures
# and the summary.
#
#   scripts/e2e.sh                 rebuild the stack from this checkout, then run all specs
#   scripts/e2e.sh --no-build csv  skip the rebuild; extra args go to Playwright
#
# One-time: `docker compose exec app vwk user create bob`, put BOB_PASSWORD in .env,
# and `cd frontend && npx playwright install chromium firefox`.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env: cp .env.example .env and edit it" >&2; exit 2; }
build=1
if [ "${1:-}" = --no-build ]; then build=0; shift; fi
set -a; . ./.env; set +a
: "${BOB_PASSWORD:?set BOB_PASSWORD in .env (the second e2e user, bob)}"
if [ "$build" = 1 ]; then
  docker compose up -d --build --wait >/dev/null 2>&1 || { docker compose ps; exit 1; }
fi
cd frontend
VWK_BASE_URL=${PUBLIC_URL%/} npm run e2e:app --silent -- --reporter=line "$@" 2>&1 |
  grep -vE '^\s*$|^\[[0-9]+/[0-9]+\] ' | tail -60
exit "${PIPESTATUS[0]}"
