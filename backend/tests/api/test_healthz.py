async def test_healthz_ok_with_live_db(client):
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


async def test_healthz_503_when_db_down(client_db_down):
    r = await client_db_down.get("/api/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "db": "down"}
