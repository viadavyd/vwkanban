# VWKanban

A fast, keyboard-first (vim-style) kanban with real-time collaboration. One
`docker compose up` runs it: PostgreSQL, the app (FastAPI) and nginx serving the web UI.
It fits a 1 GB VPS. MIT licensed.

## Quick start

You need Docker with the Compose plugin. The images are prebuilt, so nothing is compiled
on your server.

```sh
git clone https://github.com/viadavyd/vwkanban.git
cd vwkanban
cp .env.example .env
```

Edit four values in `.env`:

| Variable | Set it to |
|---|---|
| `PUBLIC_URL` | the exact address people open, e.g. `http://kanban.example.com` (scheme, host and port if not 80) |
| `POSTGRES_PASSWORD` | a long random string, e.g. from `openssl rand -hex 16` |
| `ADMIN_PASSWORD` | the first admin's password (the user is `ADMIN_USERNAME`, default `admin`) |
| `HTTP_PORT` | the host port nginx listens on (default `80`) |

Then start it and check that it is up:

```sh
docker compose up -d --wait
curl http://localhost/api/healthz
```

`curl` should print `{"status":"ok","db":"ok"}`. Use your `HTTP_PORT` if it isn't 80. Open
`PUBLIC_URL` in a browser and log in as the admin. The admin is created on first start,
when there are no users yet. Changing `ADMIN_PASSWORD` later does nothing; use
`vwk user passwd` instead.

It serves plain HTTP. For HTTPS, see [TLS](#tls-https-with-caddy).

## Accounts

There are no public signups by default. Add users from the server:

```sh
docker compose exec app vwk user create alice    # prompts for the password (8+ characters) twice
docker compose exec app vwk user passwd alice    # set a new password
docker compose exec app vwk user list
```

For scripts, `--password-stdin` reads the password from stdin:

```sh
printf '%s\n' "$PASSWORD" | docker compose exec -T app vwk user create bob --password-stdin
```

**Self-service signup:** set `ALLOW_SIGNUP=true` in `.env` and run `docker compose up -d`.
The login page then shows a "Sign up" link, and anyone who can reach the site can make an
account. A new board is private to its owner. Press `M` on a board to add members by
username.

## Keys

Everything works from the keyboard. Press `?` on any screen for the complete list.
`Esc` / `Ctrl+C` always go back one level: field → card → board → dashboard.

- **Dashboard:** `h j k l` move, `Enter` opens, `a` new board, `r` rename, `d` delete, `Q` log out.
- **Board:** `h l` columns, `j k` cards, `i` open, `a`/`A` new card below/above, `Space`
  done, `y` copy, `x` mark for move, `p` paste or move, `d` delete, `u` undo, `s a/r/c/d`
  columns, `H`/`L` move a column, `M` members, `E` export CSV, `I` import CSV.
- **Card:** `j k` rows, `i`/`a` edit in vim, `o`/`O` new child, `Space` done, `d` delete
  a child, `u` undo. In a field: full vim, plus `:w`, `:w!` (save over a teammate's
  change) and `:e!` (take theirs).

## Backup and restore

Everything lives in PostgreSQL, in the `pgdata` volume. To make a backup:

```sh
docker compose exec -T db pg_dump -U vwkanban -Fc vwkanban > vwkanban.dump
```

Copy `vwkanban.dump` off the server, e.g. from a nightly cron job. To restore it, replacing
everything in the database:

```sh
docker compose stop app
docker compose exec -T db pg_restore -U vwkanban -d vwkanban --clean --if-exists --single-transaction < vwkanban.dump
docker compose start app
```

To restore on a new server, run the quick start first, then the three commands above.

## TLS (HTTPS) with Caddy

The stack serves plain HTTP. To get HTTPS, put a proxy in front of it. With
[Caddy](https://caddyserver.com), point the domain's DNS at the server, then create three
files next to `compose.yaml`.

`Caddyfile` (Caddy gets and renews a Let's Encrypt certificate itself):

```
kanban.example.com {
	reverse_proxy web:80
}
```

`real-ip.conf`: nginx should rate-limit logins per client (5 a minute), not per proxy. It
trusts `X-Forwarded-For` only from the compose network, which only Caddy can reach once
`web` publishes no port:

```nginx
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;
set_real_ip_from 10.0.0.0/8;
real_ip_header X-Forwarded-For;
real_ip_recursive on;
```

`compose.override.yaml` (Compose reads it with `compose.yaml` automatically):

```yaml
services:
  web:
    ports: !reset []
    volumes:
      - ./real-ip.conf:/etc/nginx/conf.d/real-ip.conf:ro
  caddy:
    image: caddy:2.11.9-alpine
    ports: ["80:80", "443:443", "443:443/udp"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [web]
    mem_limit: 64m
    restart: unless-stopped

volumes:
  caddy_data:
  caddy_config:
```

Set `PUBLIC_URL=https://kanban.example.com` in `.env` (this makes the session cookie
`Secure`), then run `docker compose up -d`. If you use your own proxy instead, have it
forward to `HTTP_PORT` and set `X-Forwarded-For`, and set `set_real_ip_from` to its
address.

## Upgrade

```sh
docker compose pull && docker compose up -d
```

Database migrations run when the app starts. To stay on a release, set `VWK_VERSION` in
`.env` to a tag (default `latest`). Make a [backup](#backup-and-restore) first.

## Building the images yourself

```sh
docker compose up -d --build
```

This builds the frontend with Node inside Docker. On a small VPS, use the prebuilt
images.

## Troubleshooting

- **Logging in or saving fails with "bad or missing Origin"**: `PUBLIC_URL` isn't the
  address in the browser's address bar. Scheme, host and port must match exactly, so an
  `https://` `PUBLIC_URL` doesn't work over plain HTTP (and the `Secure` cookie wouldn't
  be sent there either).
- **Everyone gets "too many requests" at login behind a proxy**: nginx sees only the
  proxy's address. Add `real-ip.conf` as shown [above](#tls-https-with-caddy).
- **Logs**: `docker compose logs app` (or `db`, `web`). `docker compose ps` shows health.

## Checks

- `scripts/deploy-check.sh`: run in a fresh checkout (no `.env`). It does the quick start
  with generated passwords on port 8089, waits until healthy, logs in over plain HTTP,
  prints the time (must be under 3 minutes) and removes everything again. From a checkout
  that has a `.env`, run `make deploy-check`, which uses a temporary clone.
- `make perf`: every performance target of the project (deploy time, memory, bundle size,
  board load, real-time latency, UI responsiveness), enforced, on a throwaway stack. It
  needs Docker, uv, Node 22 and sudo (for `tc netem`).

Development commands (tests, local dev servers, lint) are in [`CLAUDE.md`](CLAUDE.md#commands).

## License

[MIT](LICENSE)
