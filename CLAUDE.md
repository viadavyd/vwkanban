# VWKanban

A fast, keyboard-first (vim-style), open-source web kanban. It should deploy with one `docker compose up` and support real-time team collaboration.

## Sources of truth
- `.local/notes.md` is the product spec: goals, user stories, data models, card view, CSV headers, keybinds. Check it before changing behavior. If the spec and the code disagree, ask; don't guess.
- `.local/drawing/*.png` are the UI wireframes: `login.png`, `main.png` (dashboard), `board.png`.
- `.local/plan.md` is the approved MVP plan: data model, API/WS protocol, keymap, milestones (M0–M7). Follow its milestone order.
- Keybinds are a core feature. Every user action must be reachable from the keyboard, and any change to keybinds must keep the modes consistent: dashboard → board mode → card mode → field (vim) mode, with `Esc`/`Ctrl+C` going back one level.

## Stack
- Backend: Python 3.13, FastAPI, SQLAlchemy 2.0 (async, asyncpg), Alembic, Pydantic 2, uvicorn (1 worker)
- DB: PostgreSQL 17
- Frontend: Svelte 5 + Vite + TypeScript (static SPA served by nginx); CodeMirror 6 + @replit/codemirror-vim for card fields (lazy-loaded)
- Sync: REST for load/auth/CSV/members; all board mutations are ops (WS `/api/boards/{id}/ws` or `POST /api/boards/{id}/ops`) through `sync/ops.py::apply_op`
- Deploy: Docker Compose (app, db, web=nginx) with prebuilt images; config only via `.env`
- License: MIT

## Layout
backend/vwkanban/{auth,boards,sync,csvio}, backend/migrations, backend/tests/{unit,api,ws,csv};
frontend/src/{lib/{api,sync,keys,editor},routes,components}, frontend/{tests,e2e}; docker/; compose.yaml; scripts/

## Commands (available once M0 is done)
- Run all: `cp .env.example .env && docker compose up -d` (build locally: `docker compose up -d --build`)
- Backend dev: `cd backend && uv sync && uv run uvicorn vwkanban.main:app --reload`
- Frontend dev: `cd frontend && npm ci && npm run dev` (proxies /api to :8000)
- Test: `cd backend && uv run pytest` · `cd frontend && npm test && npx playwright test`
- Perf: `make perf` (enforced on the reference machine; report-only in CI)
- Lint/format: `uv run ruff check --fix . && uv run ruff format .` · `npm run check && npm run format` · `pre-commit run -a`
- Migrate: `uv run alembic revision --autogenerate -m "..."` then `uv run alembic upgrade head` (the app container runs `upgrade head` on start)
- Users: `docker compose exec app vwk user create <name>`

## Conventions
- Every board mutation goes through `apply_op`; never write cards/statuses from a route directly.
- Every written card field updates `cards.field_meta` ({seq, client}); conflict and undo checks read it, never the event log.
- Every route/op touching a board uses the `require_member` dependency; the parametrized access-matrix test must cover new routes.
- Keys live only in `frontend/src/lib/keys/keymap.ts` with help text; the help overlay and the uniqueness test read from it. `Esc`/`Ctrl+C` always go back exactly one level (board → dashboard included).
- Blocking work (argon2, CSV parsing of large files) runs in a thread pool, never on the event loop.
- New op kinds need: schema, apply branch, client inverse (for undo), and a multi-client test.
- Ids are client-generated UUIDv7; fractional positions and card numbers are assigned server-side only.
- Migrations are additive within a release; never edit an applied migration.

## Working rules
- Build in small vertical slices (milestones from the approved plan). Each slice ends with passing tests and a working `docker compose up`.
- Real-time changes need a multi-client test, and CSV changes need a round-trip (export → import) test.
- Keep dependencies few. Fast and light matter more than features.
- Update this file when the stack, commands or conventions change.
