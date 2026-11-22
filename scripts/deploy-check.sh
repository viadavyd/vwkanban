#!/usr/bin/env bash
# Plan §7 cold-deploy check, from a checkout without a .env (the README's quick start):
# cp .env.example .env, edit 4 values, docker compose up -d → healthy, then log in over
# plain HTTP with a non-localhost hostname. Fails if that takes 180 s or more.
#
#   scripts/deploy-check.sh [--build] [--keep] [--port 8089] [--host vwk.test]
#
#   --build  build the images from this checkout instead of pulling them
#   --keep   leave the stack (and its .env) running; otherwise `down -v` at the end
#   --host   the hostname in PUBLIC_URL (curl resolves it to 127.0.0.1, so no /etc/hosts)
#
# It runs as compose project $VWK_PROJECT (default vwk-deploy-check), so it never touches
# another stack on this machine, e.g. your `vwkanban` one.
set -euo pipefail

build=() keep=0 port=8089 host=vwk.test limit=180
while [ $# -gt 0 ]; do
  case "$1" in
    --build) build=(--build) ;;
    --keep) keep=1 ;;
    --port) port=$2; shift ;;
    --host) host=$2; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
project=${VWK_PROJECT:-vwk-deploy-check}
url="http://$host:$port"

cd "$(dirname "$0")/.."
if [ -e .env ]; then
  echo "deploy-check needs a fresh .env: run it in a clean checkout (this one has a .env)" >&2
  exit 2
fi

dc() { docker compose -p "$project" "$@"; }
finish() {
  status=$?
  if [ "$status" -ne 0 ]; then dc logs --tail 50 >&2 || true; fi
  if [ "$keep" -eq 0 ]; then
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f .env
  fi
  rm -f "${jar:-}" "${headers:-}"
  exit "$status"
}
trap finish EXIT

# The 4 edits the README asks for.
cp .env.example .env
sed -i \
  -e "s|^PUBLIC_URL=.*|PUBLIC_URL=$url|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 16)|" \
  -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$(openssl rand -hex 16)|" \
  -e "s|^HTTP_PORT=.*|HTTP_PORT=$port|" \
  .env
admin=$(sed -n 's/^ADMIN_USERNAME=//p' .env)
password=$(sed -n 's/^ADMIN_PASSWORD=//p' .env)

start=$(date +%s)
dc up -d "${build[@]}" --wait --wait-timeout "$limit"

curl_() { curl -fsS --resolve "$host:$port:127.0.0.1" "$@"; }
curl_ "$url/api/healthz" | grep -q '"status":"ok"'
curl_ "$url/" | grep -q '<div id="app">'

# Log in over plain HTTP: the session cookie must be HttpOnly and not Secure.
jar=$(mktemp) headers=$(mktemp)
curl_ -D "$headers" -c "$jar" -o /dev/null -H "Origin: $url" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$admin\",\"password\":\"$password\"}" "$url/api/auth/login"
cookie=$(grep -i '^set-cookie: vwk_session=' "$headers")
echo "$cookie" | grep -qi 'httponly'
if echo "$cookie" | grep -qi 'secure'; then
  echo "FAIL: the session cookie is Secure over plain HTTP" >&2
  exit 1
fi
curl_ -b "$jar" "$url/api/auth/me" | grep -q "\"username\":\"$admin\""
elapsed=$(($(date +%s) - start))

echo "deploy-check: healthy and logged in at $url in ${elapsed} s (limit ${limit} s)"
if [ "$elapsed" -ge "$limit" ]; then
  echo "FAIL: cold deploy took ${elapsed} s" >&2
  exit 1
fi
