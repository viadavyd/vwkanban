import os
import subprocess
import sys

from sqlalchemy import text

from tests.conftest import BACKEND_DIR


def vwk(database_url: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "vwkanban.cli", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        input=stdin,
        capture_output=True,
        text=True,
    )


async def test_user_create_passwd_list(database_url, engine, make_client):
    r = vwk(database_url, "user", "create", "Bob", "--password-stdin", stdin="first-pass\n")
    assert r.returncode == 0, r.stderr
    assert "created user bob" in r.stdout

    async with engine.connect() as conn:
        h = (await conn.execute(text("SELECT password_hash FROM users"))).scalar_one()
    assert h.startswith("$argon2id$")

    dup = vwk(database_url, "user", "create", "bob", "--password-stdin", stdin="first-pass\n")
    assert dup.returncode == 1
    assert "already exists" in dup.stderr

    async with make_client() as c:
        login = {"username": "bob", "password": "first-pass"}
        assert (await c.post("/api/auth/login", json=login)).status_code == 200
        r = vwk(database_url, "user", "passwd", "bob", "--password-stdin", stdin="second-pass\n")
        assert r.returncode == 0, r.stderr
        assert (await c.get("/api/auth/me")).status_code == 401  # sessions were dropped
        assert (await c.post("/api/auth/login", json=login)).status_code == 401
        login["password"] = "second-pass"
        assert (await c.post("/api/auth/login", json=login)).status_code == 200

    r = vwk(database_url, "user", "list")
    assert r.returncode == 0
    assert r.stdout.startswith("bob\t")


def test_user_create_rejects_bad_input(database_url):
    r = vwk(database_url, "user", "create", "x", "--password-stdin", stdin="long-enough\n")
    assert r.returncode == 1
    assert "username" in r.stderr
    r = vwk(database_url, "user", "create", "carol", "--password-stdin", stdin="short\n")
    assert r.returncode == 1
    assert "password" in r.stderr
    r = vwk(database_url, "user", "passwd", "nobody", "--password-stdin", stdin="long-enough\n")
    assert r.returncode == 1
