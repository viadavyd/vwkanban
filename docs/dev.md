# Development details

Commands that CLAUDE.md only names. Read this file only when you need one of them.

## Local setup (one-time)
- Postgres for tests: `scripts/dev-db.sh` starts a throwaway container on 127.0.0.1:5432.
  The tests read `DATABASE_URL`, which defaults to it. Stop it with `docker rm -f vwk-dev-db`.
- Backend: `cd backend && uv sync`
- Frontend (Node 22): `cd frontend && npm ci && npx playwright install chromium firefox`
- e2e second user:
  1. Run `docker compose exec app vwk user create bob`.
  2. Put `BOB_PASSWORD=...` in `.env`, which is local only.
- pre-commit: `uv tool install pre-commit`. Run `npm ci` first, because the prettier hook
  uses `frontend/node_modules`.

## Dev servers
- Backend:
  ```
  cd backend
  DATABASE_URL=postgresql+asyncpg://vwkanban:vwkanban@127.0.0.1:5432/vwkanban PUBLIC_URL=http://localhost:5173 uv run uvicorn vwkanban.main:app --reload
  ```
  `PUBLIC_URL` must be the origin the browser uses, because requests are Origin-checked.
- Frontend: `cd frontend && npm run dev`. It proxies `/api` to :8000.

## Tests in detail
- Backend: `cd backend && uv run pytest`. It migrates the test DB itself. `tests/ws/` runs
  the app in a uvicorn subprocess with real `websockets` clients, and `VWK_WS_PORT` pins
  its port.
- Frontend unit: `cd frontend && npm test`. The vim spike runs with `npx playwright test`
  (`e2e/spike.spec.ts`).
- **App e2e** (`scripts/e2e.sh` wraps all of this):
  - **Command:** `cd frontend && VWK_BASE_URL=http://localhost ADMIN_USERNAME=admin ADMIN_PASSWORD=... BOB_PASSWORD=... npm run e2e:app`.
    `VWK_BASE_URL` must equal the stack's `PUBLIC_URL`.
  - **Logins:** login is rate-limited to 5/min per IP, so `auth.setup.ts` logs each user
    in once. Specs reuse the login with `test.use({ storageState: STATE })` or `BOB_STATE`.
  - **Waiting:** after a key that sends an op, and after a reload, wait with
    `settled(page)` (the sync dot is live and nothing is pending). Never sleep.
  - **Setup:** seed what a spec doesn't test with `seedBoard()`; `newCard()` makes a card
    from the keyboard.
  - **CSV import (`I`):** press `I`, then `getByTestId("csv-file").setInputFiles(...)`.
    Never wait for the `filechooser` event; it's flaky.
  - **Firefox:** the `vim:` tests in `card-mode.spec.ts` also run in Firefox.

## Perf and deploy checks
- `make perf` (`scripts/perf.sh`) runs every design §7 check with `VWK_PERF_ENFORCE=1` on a
  throwaway stack built from HEAD (project `vwk-perf`, port 8089). Commit first. It asks
  for sudo once, for netem. The individual checks, which are report-only without
  `VWK_PERF_ENFORCE=1`:
  - `scripts/deploy-check.sh`
  - `scripts/mem-check.py`
  - `npm run size`
  - `backend/tests/api/test_board_perf.py`
  - `backend/tests/ws/test_latency.py`
  - `frontend/e2e/app/board-perf.spec.ts`
- Deploy check: `make deploy-check` from any checkout (it uses a temporary clone), or
  `scripts/deploy-check.sh [--build] [--keep]` in a checkout without `.env`. It uses the
  project `vwk-deploy-check` on port 8089. CI runs it in the smoke job.

## Users and migrations
- Users:
  - `docker compose exec app vwk user create|passwd <name>`; for scripts, add `-T` and
    `--password-stdin`
  - `vwk user list`
- Migrations: `cd backend && uv run alembic revision --autogenerate -m "..."`, then
  `uv run alembic upgrade head`. The app container runs `upgrade head` on start.
