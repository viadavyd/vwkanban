#!/usr/bin/env bash
# `make perf`: every plan §7 target, enforced (VWK_PERF_ENFORCE=1), on a throwaway stack.
#
#   1. cold deploy   scripts/deploy-check.sh --build in a fresh clone of HEAD (< 180 s)
#   2. memory        scripts/mem-check.py: idle < 300 MB, 20 clients on 500 cards < 600 MB
#   3. initial JS    frontend/scripts/bundle-size.mjs: < 80 KB gz, editor lazy
#   4. board load    backend tests/api/test_board_perf.py: GET 500 cards < 150 ms
#   5. remote change backend tests/ws/test_latency.py with 20 ms netem on its port (sudo):
#                    p95 < 300 ms at 40 ops/s, apply p95 < 30 ms
#   6. UI            frontend e2e/app/board-perf.spec.ts (4× CPU throttle): key → frame
#                    p95 < 50 ms, holding j: no long task > 50 ms, interactive < 1 s
#
# The stack is compose project vwk-perf on http://localhost:$VWK_PERF_PORT (default 8089),
# built from HEAD (commit first: uncommitted changes aren't in the clone); it and the clone
# are removed at the end. Steps 3, 4 and 6 run from this checkout (its node_modules and
# uv env). Step 4 uses scripts/dev-db.sh. Needs docker, uv, node, openssl, and sudo for tc.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
port=${VWK_PERF_PORT:-8089}
url="http://localhost:$port"
project=vwk-perf
ws_port=18765
export VWK_PERF_ENFORCE=1

if [ -n "$(git -C "$root" status --porcelain)" ]; then
  echo "note: uncommitted changes are not in the measured stack (it is built from HEAD)" >&2
fi
sudo -v # ask for the password now, not halfway through

tmp=$(mktemp -d)
netem=0
cleanup() {
  status=$?
  if [ "$netem" -eq 1 ]; then sudo tc qdisc del dev lo root 2>/dev/null || true; fi
  if [ -f "$tmp/vwk/.env" ]; then
    (cd "$tmp/vwk" && docker compose -p "$project" down -v --remove-orphans >/dev/null 2>&1) || true
  fi
  rm -rf "$tmp"
  if [ "$status" -eq 0 ]; then echo "make perf: all §7 targets met"; else echo "make perf: FAILED" >&2; fi
  exit "$status"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$*"; }

step "1/6 cold deploy (fresh clone, --build)"
git clone -q "$root" "$tmp/vwk"
VWK_PROJECT=$project "$tmp/vwk/scripts/deploy-check.sh" --build --keep --host localhost --port "$port"

step "2/6 memory (idle, then 20 clients)"
(cd "$root/backend" && uv run python ../scripts/mem-check.py \
  --url "$url" --project "$project" --env "$tmp/vwk/.env")

step "3/6 initial JS"
(cd "$root/frontend" && npm run -s build >/dev/null && npm run -s size)

step "4/6 board load (500 cards)"
"$root/scripts/dev-db.sh"
(cd "$root/backend" && uv run pytest -q -s tests/api/test_board_perf.py)

step "5/6 remote change latency (20 ms netem on port $ws_port)"
netem=1
sudo tc qdisc add dev lo root handle 1: prio
sudo tc qdisc add dev lo parent 1:3 handle 30: netem delay 20ms
for dir in dport sport; do
  sudo tc filter add dev lo parent 1:0 protocol ip u32 \
    match ip "$dir" "$ws_port" 0xffff flowid 1:3
done
(cd "$root/backend" && VWK_WS_PORT=$ws_port uv run pytest -q -s tests/ws/test_latency.py)
sudo tc qdisc del dev lo root
netem=0

step "6/6 UI on a 500-card board (4× CPU throttle)"
bob_password=$(openssl rand -hex 16)
printf '%s\n' "$bob_password" |
  (cd "$tmp/vwk" && docker compose -p "$project" exec -T app vwk user create bob --password-stdin)
(
  cd "$root/frontend"
  set -a
  . "$tmp/vwk/.env"
  set +a
  BOB_USERNAME=bob BOB_PASSWORD=$bob_password VWK_BASE_URL=$url \
    npx playwright test -c playwright.app.config.ts board-perf.spec.ts --project=chromium
)
