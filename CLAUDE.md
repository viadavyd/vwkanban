# VWKanban

A fast, keyboard-first (vim-style), open-source web kanban with real-time collaboration.
It deploys with one `docker compose up`. The MVP (M0–M7) is done; work now is features
and fixes from `docs/backlog.md`.

## Read on demand, not up front
- `docs/map.md`: for each area, the files, rules and tests. **Start here** and read only
  the files your area lists.
- `docs/design.md`: the behaviour spec (data model, ops/WS protocol, conflicts, CSV, modes,
  perf targets). `plan §N` in code comments means `docs/design.md §N`. If the code and the
  design disagree, ask.
- `docs/dev.md`: detailed commands (dev servers, e2e, perf, deploy check, migrations).
- `docs/backlog.md`: bugs and features. Update it when you start or finish an item.

## Stack
- **Backend:** Python 3.13, FastAPI, async SQLAlchemy 2 + asyncpg, Alembic, Pydantic 2,
  uvicorn (1 worker, `websockets`)
- **DB:** PostgreSQL 17
- **Frontend:** Svelte 5 + Vite + TS SPA behind nginx; CodeMirror 6 + vim, lazy-loaded
- **Deploy:** Docker Compose (app, db, web) with GHCR images
- **License:** MIT

## Commands
- **Fast gate:** `scripts/check.sh [backend|frontend] [pytest args]` runs lint, types and
  all unit/API/WS tests, and prints quiet output. While you iterate, run only your area
  (e.g. `scripts/check.sh backend -k csv`). Run the full gate once before the PR.
- **Browser e2e:** `scripts/e2e.sh [--no-build] [spec filter]`. It rebuilds the local stack
  from this checkout first, unless you pass `--no-build`.
- **Format:** `cd backend && uv run ruff format . && uv run ruff check --fix .` ·
  `cd frontend && npm run format`
- **Local stack:** `docker compose up -d --build`, at `PUBLIC_URL` from `.env`

## Rules that apply everywhere
- **Board mutations:** every one goes through `sync/ops.py::apply_op`. Never write
  cards or statuses from a route.
- **Positions and numbers:** fractional positions and card numbers are assigned only by
  the server, and ids are client UUIDv7.
- **A new op kind** needs a schema, an apply branch, a client inverse (undo) and a
  multi-client test.
- **`field_meta`:** every written field updates it, and conflict and undo checks read it,
  never the event log.
- **Board access:** every board route uses `require_member` / `require_owner` and is
  listed in `BOARD_ROUTES`.
- **API errors and Origin:** errors are `{error:{code,message}}` via `ApiError`.
  State-changing requests are Origin-checked.
- **Keys:** they live only in `frontend/src/lib/keys/keymap.ts`, with help text. There is
  one capture-phase listener (`pushMode()`), and you must never add another `keydown`
  listener. `Esc`/`Ctrl+C` go back exactly one level: field → card → board → dashboard.
  Every action must be reachable from the keyboard.
- **Never lose user text:** drafts that can't be saved go to the register.
- **Blocking work** (argon2, CSV parsing) runs in a thread pool.
- **Migrations** are additive. Never edit an applied one.
- **Tests:** real-time changes need a multi-client test, and CSV changes need an
  export → import round-trip test. In e2e, wait with `settled(page)` and never sleep.
- **Dependencies:** keep them few. Ask before adding one. Fast and light beat features.

## Workflow
- Use `/feature <item>` or `/fix <bug>` (skills in `.claude/skills/`). Work on a branch
  and keep to one task per session.
- When you change behaviour, update `docs/design.md`. When files or areas move, update
  `docs/map.md`. When commands change, update this file or `docs/dev.md`.
