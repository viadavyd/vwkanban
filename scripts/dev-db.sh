#!/usr/bin/env sh
# Throwaway Postgres for local pytest/dev on 127.0.0.1:5432.
# Matches tests/conftest.py's default DATABASE_URL. Stop with: docker rm -f vwk-dev-db
set -eu
name=vwk-dev-db
if docker ps --format '{{.Names}}' | grep -qx "$name"; then
  echo "$name already running"; exit 0
fi
docker rm -f "$name" >/dev/null 2>&1 || true
docker run -d --name "$name" -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=vwkanban -e POSTGRES_PASSWORD=vwkanban -e POSTGRES_DB=vwkanban \
  postgres:17.12-alpine >/dev/null
until docker exec "$name" pg_isready -U vwkanban >/dev/null 2>&1; do sleep 0.5; done
echo "$name ready: postgresql+asyncpg://vwkanban:vwkanban@127.0.0.1:5432/vwkanban"
