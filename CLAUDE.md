# VWKanban

A fast, keyboard-first (vim-style), open-source web kanban. It should deploy with one `docker compose up` and support real-time team collaboration.

## Sources of truth
- `.local/notes.md` is the product spec: goals, user stories, data models, card view, CSV headers, keybinds. Check it before changing behavior. If the spec and the code disagree, ask; don't guess.
- `.local/drawing/*.png` are the UI wireframes: `login.png`, `main.png` (dashboard), `board.png`.
- `.local/plan.md` is the approved MVP plan: data model, API/WS protocol, keymap, milestones (M0–M7). Follow its milestone order.
- Keybinds are a core feature. Every user action must be reachable from the keyboard, and any change to keybinds must keep the modes consistent: dashboard → board mode → card mode → field (vim) mode, with `Esc`/`Ctrl+C` going back one level.

## Stack
- Backend: Python 3.13, FastAPI, SQLAlchemy 2.0 (async, asyncpg), Alembic, Pydantic 2, uvicorn (1 worker, `websockets` for WS)
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
- Test: `cd backend && uv run pytest` (migrates the test DB itself; `tests/ws/` runs the app in a uvicorn subprocess with real `websockets` clients; `VWK_WS_PORT` pins its port) · `cd frontend && npm test && npx playwright test` (one-time: `npx playwright install chromium firefox`; this runs the vim spike, `e2e/spike.spec.ts`)
- App e2e (against a running stack; `VWK_BASE_URL` must equal its `PUBLIC_URL`): `cd frontend && VWK_BASE_URL=http://localhost ADMIN_USERNAME=admin ADMIN_PASSWORD=... BOB_PASSWORD=... npm run e2e:app` (`e2e/app/`; the two-user specs need a second user: `docker compose exec app vwk user create bob`, `BOB_USERNAME` defaults to `bob`. Login is rate-limited to 5/min per IP, so `auth.setup.ts` logs each user in once and specs that don't test login reuse `storageState` via `test.use({ storageState: STATE })` or `BOB_STATE`. After a key that sends an op, and after a reload, wait with `settled(page)` (the sync dot: live, nothing pending); never sleep. Seed what a spec doesn't test with `seedBoard()`; `newCard()` makes a card from the keyboard. The `vim:` tests of `card-mode.spec.ts` also run in the `firefox` project)
- Perf: report-only by default; `VWK_PERF_ENFORCE=1` makes `backend/tests/api/test_board_perf.py`, `backend/tests/ws/test_latency.py` (remote change at 40 ops/s; CI adds 20 ms netem on `VWK_WS_PORT`) and `frontend/e2e/app/board-perf.spec.ts` (500 cards, 4× CPU throttle) fail on a missed §7 target. From M7: `make perf` (enforced on the reference machine)
- Lint/format: `uv run ruff check --fix . && uv run ruff format .` · `npm run check && npm run format` · `pre-commit run -a` (one-time: `uv tool install pre-commit`; run `npm ci` first, the prettier hook uses `frontend/node_modules`)
- Migrate: `uv run alembic revision --autogenerate -m "..."` then `uv run alembic upgrade head` (the app container runs `upgrade head` on start)
- Users: `docker compose exec app vwk user create|passwd <name>` · `vwk user list` (the first admin comes from `ADMIN_USERNAME`/`ADMIN_PASSWORD` when no users exist)

## Conventions
- Every board mutation goes through `apply_op`; never write cards/statuses from a route directly. Op kinds live in `sync/schemas.py` (one model per kind, `extra="forbid"`); a reject is the error envelope plus `op_id` and `current` (the entity's server state or null) and consumes no seq. Card positions come only from `sync/fracindex.py::key_between`.
- Text fields (`title`, `description`, `tags`, `date`) of `card.update` are refused with `conflict` when another client wrote the field after the op's `base_seq` (`_Ctx.stale`); `is_done` and moves are last write wins. The client freezes `base_seq` when a field is entered and moves it only on its own ack for that field (`lib/editor/session.ts::FieldSession`); `:w!` resends with the current seq, `:e!` takes the server value. A child is `card.create` with `parent_id` (depth 1).
- Frontend board state lives in `lib/sync/store.ts` (`BoardStore`: confirmed + pending ops, optimistic view; `view.kids` holds each card's children in order). `submit()` resolves with the server's answer (ack seq or reject). It sends ops over the board WebSocket (`lib/sync/socket.ts`), pipelined; after a reconnect it re-sends every unanswered op with the same `op_id`, and ops queue in memory while offline. Events apply strictly in seq order (a gap waits 1 s, then resync). `POST /ops` stays for the API and tests.
- Real time: `apply_op` broadcasts each event to the board's sockets through `sync/hub.py` (`app.state.hub`; one outbound queue per socket, never awaited under the board lock). WS messages are capped at 128 KB (`--ws-max-size 131072`, so a 20 000-char description fits). The WS handshake (`sync/ws.py`) checks Origin with `origin_allowed` (4400), the session cookie (4401), the board (4404) and membership (4403) before registering, then answers `hello` under the board lock. Logout, board delete and member removal close the affected sockets (4401/4404/4403).
- Undo: `BoardStore.submit()` pushes the op's inverse (`ops.ts::inverseOf`, computed from the view just before the op); `BoardStore.undo()` sends it with `undo: true` and `base_seq` = the seq the original op got (filled in at send time). The board register (`y`/`d` copy, `x` move mark) is `lib/sync/register.ts`.
- Every written card or column field updates `field_meta` ({seq, client}) on `cards` / `statuses`; conflict and undo checks (`_Ctx.undo_check`) read it, never the event log. `status.delete` is refused while the column has live cards and purges its soft-deleted ones.
- API errors are `{error: {code, message}}` (raise `vwkanban.errors.ApiError`). Every state-changing `/api` request must send an `Origin` equal to `PUBLIC_URL`'s (`auth/origin.py`); the WS handshake reuses `origin_allowed`.
- Every route/op touching a board uses `require_member` (or `require_owner`) from `boards/deps.py`: non-members get 404, editors get 403 on owner-only routes. The access-matrix test (`tests/api/test_boards.py::BOARD_ROUTES`) must list every `/boards/{board_id}*` route; a guard test reads the OpenAPI paths and fails on a missing one.
- `position` columns use `COLLATE "C"`: fractional keys compare byte-wise, never by locale.
- Keys live only in `frontend/src/lib/keys/keymap.ts` with help text; the help overlay and the uniqueness test read from it. `Esc`/`Ctrl+C` always go back exactly one level (board → dashboard included). Screens and overlays bind keys by pushing a mode with `pushMode()` (`lib/keys/dispatch.ts`, one capture-phase listener); never add another `keydown` listener for app keys. Ex commands (`:w`, `:e`, with `!`) are `EX_COMMANDS` in keymap.ts.
- Card mode (`components/CardView.svelte`) and field mode: a field is a `lib/editor/VimField.svelte`, which pushes the `field` mode with a bridge. In a field the dispatcher binds only Esc/Ctrl+C, and leaves only from plain vim NORMAL (`lib/editor/bridge.ts::shouldLeaveField`); keys typed while the editor loads are queued and replayed. Push `card`/`field` modes during component init, not in an `$effect`, so a child's mode sits on top. Leaving a field saves it; a draft that can't be saved stays on its row, and closing the card puts unsaved drafts in the register (never lose text).
- `lib/editor/vim.ts` is the only module that imports CodeMirror; it is reached only through `lib/editor/load.ts` (`import()`), on the first card open. Keep CodeMirror out of the entry chunk.
- Blocking work (argon2, CSV parsing of large files) runs in a thread pool, never on the event loop.
- New op kinds need: schema, apply branch, client inverse (for undo), and a multi-client test.
- Ids are client-generated UUIDv7; fractional positions and card numbers are assigned server-side only.
- Migrations are additive within a release; never edit an applied migration.

## Working rules
- Build in small vertical slices (milestones from the approved plan). Each slice ends with passing tests and a working `docker compose up`.
- Real-time changes need a multi-client test, and CSV changes need a round-trip (export → import) test.
- Keep dependencies few. Fast and light matter more than features.
- Update this file when the stack, commands or conventions change.
