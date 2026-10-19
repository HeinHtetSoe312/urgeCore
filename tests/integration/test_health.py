async def test_liveness(client):
    response = await client.get("/health/liveness")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_checks_db_and_redis(client):
    response = await client.get("/health/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_correlation_id_is_echoed(client):
    response = await client.get("/health/liveness", headers={"X-Correlation-ID": "abc-123"})
    assert response.headers["x-correlation-id"] == "abc-123"


async def test_unsafe_correlation_id_is_replaced(client):
    response = await client.get("/health/liveness", headers={"X-Correlation-ID": "bad value!"})
    assert response.headers["x-correlation-id"] != "bad value!"
    assert len(response.headers["x-correlation-id"]) == 32
