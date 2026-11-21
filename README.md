# VWKanban

A fast, keyboard-first (vim-style) kanban with real-time collaboration. MIT licensed.

## Quick start

```sh
cp .env.example .env        # edit PUBLIC_URL and the passwords
docker compose up -d        # or: docker compose up -d --build
curl http://localhost/api/healthz
```

Open `PUBLIC_URL` in a browser and log in as `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`.
That admin is created on first start, when there are no users yet.

### Accounts

- More users: `docker compose exec app vwk user create <name>` (prompts for a password),
  `vwk user passwd <name>`, `vwk user list`.
- Self-service signup: set `ALLOW_SIGNUP=true` in `.env`; the login page then shows a "Sign up" link.
- `PUBLIC_URL` must be the exact address users open (scheme, host, port): writes are
  rejected when the browser's `Origin` differs, and an `https://` URL makes the session
  cookie `Secure`.

### Keys

Everything works from the keyboard; press `?` on any screen for its keys. On the dashboard:
`h j k l` move, `Enter` opens a board, `a` creates, `r` renames, `d` deletes (confirm with
`y`), `Q` logs out. `Esc` / `Ctrl+C` always go back one level.

Full deployment docs come with milestone M7.
