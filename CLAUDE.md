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

## Commands
- Run all: `cp .env.example .env && docker compose up -d` (build locally: `docker compose up -d --build`)
- Local Postgres for backend dev/tests: `scripts/dev-db.sh` (throwaway container on 127.0.0.1:5432; tests read `DATABASE_URL`, defaulting to it)
- Backend dev: `cd backend && uv sync && DATABASE_URL=postgresql+asyncpg://vwkanban:vwkanban@127.0.0.1:5432/vwkanban PUBLIC_URL=http://localhost:5173 uv run uvicorn vwkanban.main:app --reload` (`PUBLIC_URL` must be the origin the browser uses: state-changing requests are Origin-checked)
- Frontend dev (Node 22): `cd frontend && npm ci && npm run dev` (proxies /api to :8000)
- Test: `cd backend && uv run pytest` (migrates the test DB itself) · `cd frontend && npm test && npx playwright test` (one-time: `npx playwright install chromium`; this runs the vim spike, `e2e/spike.spec.ts`)
- App e2e (against a running stack; `VWK_BASE_URL` must equal its `PUBLIC_URL`): `cd frontend && VWK_BASE_URL=http://localhost ADMIN_USERNAME=admin ADMIN_PASSWORD=... npm run e2e:app` (`e2e/app/`; login is rate-limited to 5/min per IP, so `auth.setup.ts` logs in once and specs that don't test login reuse its `storageState` via `test.use({ storageState: STATE })`)
- Perf: report-only by default; `VWK_PERF_ENFORCE=1` makes `backend/tests/api/test_board_perf.py` and `frontend/e2e/app/board-perf.spec.ts` (500 cards, 4× CPU throttle) fail on a missed §7 target. From M7: `make perf` (enforced on the reference machine)
- Lint/format: `uv run ruff check --fix . && uv run ruff format .` · `npm run check && npm run format` · `pre-commit run -a` (one-time: `uv tool install pre-commit`; run `npm ci` first, the prettier hook uses `frontend/node_modules`)
- Migrate: `uv run alembic revision --autogenerate -m "..."` then `uv run alembic upgrade head` (the app container runs `upgrade head` on start)
- Users: `docker compose exec app vwk user create|passwd <name>` · `vwk user list` (the first admin comes from `ADMIN_USERNAME`/`ADMIN_PASSWORD` when no users exist)

## Conventions
- Every board mutation goes through `apply_op`; never write cards/statuses from a route directly. Op kinds live in `sync/schemas.py` (one model per kind, `extra="forbid"`); a reject is the error envelope plus `op_id` and `current` (the entity's server state or null) and consumes no seq. Card positions come only from `sync/fracindex.py::key_between`.
- Frontend board state lives in `lib/sync/store.ts` (`BoardStore`: confirmed + pending ops, optimistic view). Until the WebSocket (M4) it sends ops one at a time over `POST /ops`; a network error/5xx retries the same `op_id`.
- Every written card field updates `cards.field_meta` ({seq, client}); conflict and undo checks read it, never the event log.
- API errors are `{error: {code, message}}` (raise `vwkanban.errors.ApiError`). Every state-changing `/api` request must send an `Origin` equal to `PUBLIC_URL`'s (`auth/origin.py`); the WS handshake reuses `origin_allowed`.
- Every route/op touching a board uses `require_member` (or `require_owner`) from `boards/deps.py`: non-members get 404, editors get 403 on owner-only routes. The access-matrix test (`tests/api/test_boards.py::BOARD_ROUTES`) must list every `/boards/{board_id}*` route; a guard test reads the OpenAPI paths and fails on a missing one.
- `position` columns use `COLLATE "C"`: fractional keys compare byte-wise, never by locale.
- Keys live only in `frontend/src/lib/keys/keymap.ts` with help text; the help overlay and the uniqueness test read from it. `Esc`/`Ctrl+C` always go back exactly one level (board → dashboard included). Screens and overlays bind keys by pushing a mode with `pushMode()` (`lib/keys/dispatch.ts`, one capture-phase listener); never add another `keydown` listener for app keys.
- Blocking work (argon2, CSV parsing of large files) runs in a thread pool, never on the event loop.
- New op kinds need: schema, apply branch, client inverse (for undo), and a multi-client test.
- Ids are client-generated UUIDv7; fractional positions and card numbers are assigned server-side only.
- Migrations are additive within a release; never edit an applied migration.

## Working rules
- Build in small vertical slices (milestones from the approved plan). Each slice ends with passing tests and a working `docker compose up`.
- Real-time changes need a multi-client test, and CSV changes need a round-trip (export → import) test.
- Keep dependencies few. Fast and light matter more than features.
- Update this file when the stack, commands or conventions change.
