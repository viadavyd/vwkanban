from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.api.helpers import add_user
from vwkanban.auth.sessions import COOKIE_NAME, SESSION_TTL

PW = "s3cret-pass"


async def login(c, username="alice", password=PW):
    return await c.post("/api/auth/login", json={"username": username, "password": password})


async def session_count(engine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM sessions"))).scalar_one()


# --- login / me / logout -------------------------------------------------------------


async def test_login_me_logout(client, engine):
    await add_user(engine, "alice", PW)
    r = await login(client)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert client.cookies.get(COOKIE_NAME)

    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
    assert await session_count(engine) == 0
    assert COOKIE_NAME not in client.cookies

    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthenticated", "message": "not logged in"}}


async def test_login_is_case_insensitive(client, engine):
    await add_user(engine, "alice", PW)
    r = await login(client, username="  ALICE ")
    assert r.status_code == 200


async def test_relogin_replaces_old_session(client, engine):
    await add_user(engine, "alice", PW)
    await login(client)
    await login(client)
    assert await session_count(engine) == 1


async def test_wrong_password_and_unknown_user_look_the_same(client, engine):
    await add_user(engine, "alice", PW)
    wrong = await login(client, password="nope-nope")
    unknown = await login(client, username="bob")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "unauthenticated"
    assert "set-cookie" not in wrong.headers
    assert await session_count(engine) == 0


async def test_logout_without_session_clears_cookie(client):
    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()


async def test_logout_with_expired_session_clears_cookie(client, engine):
    await add_user(engine, "alice", PW)
    await login(client)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))
    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
    header = r.headers["set-cookie"].lower()
    assert header.startswith(f"{COOKIE_NAME}=")
    assert "max-age=0" in header
    assert await session_count(engine) == 0


async def test_unknown_cookie_is_401(client):
    client.cookies.set(COOKIE_NAME, "forged")
    assert (await client.get("/api/auth/me")).status_code == 401


# --- expiry ------------------------------------------------------------------------


async def test_expired_session_is_rejected_and_deleted(client, engine):
    await add_user(engine, "alice", PW)
    await login(client)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert await session_count(engine) == 0


async def test_session_slides_when_older_than_a_day(client, engine):
    await add_user(engine, "alice", PW)
    await login(client)

    fresh = await client.get("/api/auth/me")
    assert "set-cookie" not in fresh.headers  # no write on every request

    async with engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET expires_at = now() + interval '10 days'"))
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert f"{COOKIE_NAME}=" in r.headers["set-cookie"]
    async with engine.connect() as conn:
        expires = (await conn.execute(text("SELECT expires_at FROM sessions"))).scalar_one()
    assert expires > datetime.now(UTC) + SESSION_TTL - timedelta(minutes=1)


async def test_startup_purges_expired_sessions(make_client, engine):
    await add_user(engine, "alice", PW)
    async with make_client() as c:
        await login(c)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE sessions SET expires_at = now() - interval '1 day'"))
    async with make_client() as c:
        async with c.app.router.lifespan_context(c.app):
            pass
    assert await session_count(engine) == 0


# --- Origin (CSRF) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "status"),
    [
        (None, 403),
        ("http://evil.test", 403),
        ("https://vwk.test", 403),  # scheme differs
        ("http://vwk.test:8080", 403),  # port differs
        ("null", 403),
        ("http://vwk.test", 200),
        ("HTTP://VWK.TEST:80", 200),  # normalised
    ],
)
async def test_origin_check_on_post(make_client, engine, origin, status):
    await add_user(engine, "alice", PW)
    async with make_client(origin=origin) as c:
        r = await login(c)
    assert r.status_code == status
    if status == 403:
        assert r.json()["error"]["code"] == "forbidden"


async def test_get_needs_no_origin(make_client):
    async with make_client(origin=None) as c:
        assert (await c.get("/api/auth/config")).status_code == 200
        assert (await c.get("/api/healthz")).status_code == 200


async def test_origin_follows_public_url_port(make_client, engine):
    await add_user(engine, "alice", PW)
    async with make_client(public_url="http://localhost:5173", origin="http://localhost:5173") as c:
        assert (await login(c)).status_code == 200


# --- signup flag -------------------------------------------------------------------


async def test_config_reports_signup_flag(make_client):
    async with make_client() as c:
        assert (await c.get("/api/auth/config")).json() == {"signup_enabled": False}
    async with make_client(allow_signup=True) as c:
        assert (await c.get("/api/auth/config")).json() == {"signup_enabled": True}


@pytest.mark.parametrize(
    "content",
    [
        '{"username": "carol", "password": "s3cret-pass"}',
        "{}",
        '{"username": "x", "password": "s3cret-pass"}',
        '{"username": "carol", "password": "short"}',
        "not json",
        "",
    ],
)
async def test_signup_404_when_disabled(client, engine, content):
    r = await client.post(
        "/api/auth/signup", content=content, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one() == 0


async def test_signup_creates_user_and_logs_in(make_client, engine):
    async with make_client(allow_signup=True) as c:
        r = await c.post("/api/auth/signup", json={"username": "Carol", "password": PW})
        assert r.status_code == 200
        assert r.json()["username"] == "carol"
        assert (await c.get("/api/auth/me")).json()["username"] == "carol"
    async with make_client() as c:
        assert (await login(c, username="carol")).status_code == 200


async def test_signup_duplicate_is_409(make_client, engine):
    await add_user(engine, "carol", PW)
    async with make_client(allow_signup=True) as c:
        r = await c.post("/api/auth/signup", json={"username": "CAROL", "password": PW})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "carol", "password": "short"},
        {"username": "x", "password": PW},
        {"username": "bad name", "password": PW},
        {"username": "carol"},
        "not json",
    ],
)
async def test_signup_validation(make_client, body):
    async with make_client(allow_signup=True) as c:
        if isinstance(body, str):
            r = await c.post("/api/auth/signup", content=body)
        else:
            r = await c.post("/api/auth/signup", json=body)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation"
    assert err["message"]


# --- cookie flags ------------------------------------------------------------------


def cookie_attrs(set_cookie: str) -> set[str]:
    return {p.strip().split("=")[0].lower() for p in set_cookie.split(";")[1:]}


async def test_cookie_flags_on_http(client, engine):
    await add_user(engine, "alice", PW)
    r = await login(client)
    header = r.headers["set-cookie"]
    attrs = cookie_attrs(header)
    assert {"httponly", "path", "max-age", "samesite"} <= attrs
    assert "samesite=lax" in header.lower()
    assert "secure" not in attrs


async def test_cookie_secure_on_https_public_url(make_client, engine):
    await add_user(engine, "alice", PW)
    async with make_client(public_url="https://vwk.test", origin="https://vwk.test") as c:
        r = await login(c)
    assert r.status_code == 200
    attrs = cookie_attrs(r.headers["set-cookie"])
    assert {"secure", "httponly"} <= attrs


@pytest.mark.parametrize(
    ("public_url", "override", "secure"),
    [
        ("http://vwk.test", True, True),
        ("https://vwk.test", False, False),
    ],
)
async def test_cookie_secure_override(make_client, engine, public_url, override, secure):
    await add_user(engine, "alice", PW)
    origin = public_url
    async with make_client(public_url=public_url, origin=origin, cookie_secure=override) as c:
        r = await login(c)
    assert ("secure" in cookie_attrs(r.headers["set-cookie"])) is secure


async def test_logout_clears_cookie(client, engine):
    await add_user(engine, "alice", PW)
    await login(client)
    r = await client.post("/api/auth/logout")
    header = r.headers["set-cookie"].lower()
    assert header.startswith(f"{COOKIE_NAME}=")
    assert "max-age=0" in header


# --- storage -----------------------------------------------------------------------


async def test_stored_hash_is_argon2id(make_client, engine):
    async with make_client(allow_signup=True) as c:
        await c.post("/api/auth/signup", json={"username": "dave", "password": PW})
    async with engine.connect() as conn:
        h = (await conn.execute(text("SELECT password_hash FROM users"))).scalar_one()
        token_hash = (await conn.execute(text("SELECT id FROM sessions"))).scalar_one()
    assert h.startswith("$argon2id$")
    assert len(token_hash) == 64  # sha256 hex, never the raw token
