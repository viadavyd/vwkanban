# Code map

Find your area below and read only the files it lists. Each area gives its files, the
rules that are easy to break, and the tests that cover it. Behaviour lives in
`docs/design.md` (§N).

## Auth: login, sessions, users (design §3.1)
- **Backend:** `backend/vwkanban/auth/`:
  - `routes.py`: the login, signup, logout and me endpoints
  - `sessions.py`: the cookie token, stored as sha256
  - `passwords.py`: argon2 in the thread pool, limited to 2
  - `origin.py`: CSRF; `origin_allowed` is reused by the WS
  - `bootstrap.py`: the admin from `.env`
  - `users.py`, `validation.py`
  - `deps.py`: the current user
  - also `cli.py` (`vwk user`) and `config.py` (`PUBLIC_URL` → secure cookies)
- **Frontend:** `routes/Login.svelte`, `lib/api/auth.ts`
- **Rules:**
  - Every state-changing `/api` request is Origin-checked, which `main.py` sets up through
    the router dependency.
  - Hashing never runs on the event loop.
- **Tests:** `tests/api/test_auth.py`, `test_bootstrap.py`, `test_cli.py`,
  `tests/unit/test_passwords.py`, `e2e/app/login.spec.ts`

## Boards, dashboard, members (design §3.1)
- **Backend:** `backend/vwkanban/boards/`:
  - `routes.py`: CRUD; it also seeds the columns
  - `summary.py`: the dashboard tiles
  - `members.py`
  - `deps.py`: `require_member` / `require_owner`
  - `models.py` (the whole schema), `schemas.py`
- **Frontend:** `routes/Dashboard.svelte`, `components/BoardTile.svelte`,
  `components/MembersOverlay.svelte`, `lib/keys/grid.ts`, `lib/api/boards.ts`
- **Rules:**
  - Every `/boards/{board_id}*` route uses `require_member` (or `require_owner`).
    Non-members get 404, and editors get 403 on owner-only routes.
  - Add each new route to `tests/api/test_boards.py::BOARD_ROUTES`. A guard test fails on
    any route that's missing.
- **Tests:** `tests/api/test_boards.py`, `test_members.py`, `test_board_schema.py`,
  `tests/ws/test_members.py`, `e2e/app/dashboard.spec.ts`

## Ops and the apply pipeline (design §3.2, §3.3)
- **Backend:** `backend/vwkanban/sync/`:
  - `ops.py`: `apply_op` and `apply_import`; the only writer of cards and statuses
  - `schemas.py`: one model per op kind, `extra="forbid"`
  - `fracindex.py`: `key_between`, the only source of positions
  - `routes.py`: `POST /ops`
  - `models.py`: board_events
- **Rules:**
  - Never write cards or statuses from a route.
  - A reject is the error envelope plus `op_id` and `current`, and consumes no seq.
  - Every written field updates `field_meta`. The checks are `_Ctx.stale` (text conflict)
    and `_Ctx.undo_check`.
  - Ids are client UUIDv7. Positions and numbers are assigned by the server.
  - **A new op kind needs:**
    - a schema in `sync/schemas.py`
    - an apply branch in `ops.py`
    - a builder and inverse in `frontend/src/lib/sync/ops.ts::inverseOf`
    - a multi-client test in `tests/ws/`
- **Tests:** `tests/api/test_ops*.py`, `tests/unit/test_fracindex.py`, `tests/ws/test_walkthroughs.py`

## Real time: WS, hub, presence (design §3.2, §3.4)
- **Backend:**
  - `sync/ws.py`: the handshake checks, in this order: Origin 4400 → session 4401 →
    board 4404 → member 4403. It answers `hello` under the board lock.
  - `sync/hub.py`: one outbound queue per socket, never awaited under the lock.
- **Frontend:**
  - `lib/sync/socket.ts`: reconnect and pipelined sends
  - `lib/sync/store.ts`: `BoardStore`, which holds confirmed + pending; `view.kids` holds
    children; `submit()` resolves with the ack or reject; `undo()`
  - `components/TopBar.svelte`: presence and the sync dot
- **Rules:**
  - Events apply strictly in seq order; a gap waits 1 s, then the client resyncs.
  - Resends keep their `op_id`.
  - Logout, board delete and member removal close the affected sockets.
  - Every realtime change needs a multi-client test.
- **Tests:** `tests/ws/test_ws.py`, `test_storm.py`, `test_latency.py`,
  `frontend/tests/store.test.ts`, `socket.test.ts`, `e2e/app/realtime.spec.ts`

## Board view and board keys (design §4.3, §4.4)
- **Frontend:**
  - `routes/Board.svelte`: board actions, CSV and overlays
  - `components/Column.svelte`, `CardTile.svelte`
  - `lib/keys/board.ts`: selection movement
  - `lib/sync/register.ts`: `y`, `d` and the x mark
  - `lib/colors.ts`: matches the backend `COLORS`
- **Undo:** `submit()` pushes `inverseOf(op)`, and `undo()` sends it with `undo: true`
  and `base_seq` set to the seq the original op got.
- **Tests:** `frontend/tests/board-nav.test.ts`, `register.test.ts`, `ops.test.ts`,
  `e2e/app/board.spec.ts`, `board-ops.spec.ts`, `board-perf.spec.ts`

## Card mode and vim fields (design §4.2)
- **Frontend:**
  - `components/CardView.svelte`
  - `lib/editor/VimField.svelte`: pushes the `field` mode
  - `lib/editor/bridge.ts::shouldLeaveField`
  - `lib/editor/session.ts::FieldSession`: the frozen `base_seq`, `:w!`, `:e!`
  - `lib/editor/vim.ts`: the only CodeMirror import
  - `lib/editor/load.ts`: the dynamic `import()`
- **Rules:**
  - Keep CodeMirror out of the entry chunk; `npm run size` checks it.
  - Push the `card` and `field` modes during component init, not in `$effect`.
  - Keys typed while the editor loads are queued and replayed.
  - Never lose text: an unsaved draft goes to the register.
- **Tests:** `frontend/tests/session.test.ts`, `bridge.test.ts`, `tests/ws/test_card_mode.py`,
  `e2e/app/card-mode.spec.ts` (the `vim:` tests also run in Firefox), `card-realtime.spec.ts`

## Keys and modes (design §4.2, §4.3)
- **Frontend:**
  - `lib/keys/keymap.ts`: every key, with help text. `HELP_SECTIONS` / `helpRows()` and
    `EX_COMMANDS` are here too.
  - `lib/keys/dispatch.ts`: the single capture-phase listener and `pushMode()`
  - `components/HelpOverlay.svelte`
- **Rules:**
  - Keys are defined only in keymap.ts. Never add another `keydown` listener.
  - `Esc` / `Ctrl+C` go back exactly one level.
  - A new mode or overlay must go into `HELP_SECTIONS` for every screen that opens it.
- **Tests:** `frontend/tests/keymap.test.ts` (uniqueness and help coverage),
  `dispatch.test.ts`, `e2e/app/help.spec.ts`

## CSV (design §3.6)
- **Backend:** `backend/vwkanban/csvio/`:
  - `routes.py`
  - `export.py`
  - `import_.py::parse`: pure; runs in the thread pool and reports every bad row
  - `format.py`: the headers and the formula escape
  - The write path is `sync/ops.py::apply_import`.
- **Frontend:** `routes/Board.svelte` (`exportCsv`, `pickCsv`, `picked`, `confirmImport`)
- **Rules:**
  - Clients never apply `board.import`; they resync instead.
  - Every CSV change needs an export → import round-trip test.
- **Tests:** `tests/csv/`, `tests/unit/test_csv_*.py`, `tests/ws/test_csv.py`, `e2e/app/csv.spec.ts`

## DB and migrations
- **Location:** `backend/migrations/versions/000N_*.py`; the models live in each package's
  `models.py`.
- **Rules:**
  - Migrations are additive.
  - Never edit an applied migration. Create a new one with
    `uv run alembic revision --autogenerate -m "..."`.
  - The app runs `upgrade head` on start.

## Deploy, CI, perf
- `compose.yaml`, `docker/{app,web}.Dockerfile`, `docker/nginx.conf`, `.env.example`
- `.github/workflows/ci.yml`: backend, frontend, the smoke test plus deploy-check, e2e, and
  publishing the images
- `scripts/`:
  - `dev-db.sh`
  - `check.sh`: the fast local gate
  - `e2e.sh`
  - `perf.sh`, `deploy-check.sh`, `mem-check.py`
  - also `Makefile`, `frontend/scripts/bundle-size.mjs`
- `README.md` is the user-facing deploy guide. Every command in it must have been run as
  written.

## Leftovers
- `frontend/src/spike/` and `e2e/spike.spec.ts` are the M0 vim spike. They run under
  `npx playwright test` with the default config.
