VALID = {"username": "Alice_01", "password": "correct-horse-battery"}


async def register(client, payload=None):
    return await client.post("/api/v1/auth/register", json=payload or VALID)


async def login(client, payload=None):
    return await client.post("/api/v1/auth/login", json=payload or VALID)


async def test_register_login_and_me(client):
    created = await register(client)
    assert created.status_code == 201
    body = created.json()
    assert body["username"] == "alice_01"  # normalised to lower case
    assert body["balance"] == "100.00"
    assert "password" not in body
    assert "password_hash" not in body

    token = (await login(client)).json()["access_token"]
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice_01"


async def test_duplicate_username_is_a_conflict(client):
    await register(client)
    second = await register(client)
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")


async def test_wrong_password_and_unknown_user_look_identical(client):
    await register(client)
    wrong_password = await login(client, {"username": "alice_01", "password": "not-the-password"})
    unknown_user = await login(client, {"username": "nobody", "password": "not-the-password"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


async def test_me_requires_a_token(client):
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_garbage_token_is_rejected(client):
    response = await client.get("/api/v1/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


async def test_unknown_fields_rejected_and_password_not_echoed(client):
    payload = {**VALID, "balance": 1000000}  # mass-assignment attempt
    response = await register(client, payload)
    assert response.status_code == 422
    assert "correct-horse-battery" not in response.text


async def test_short_password_rejected(client):
    response = await register(client, {"username": "bob", "password": "short"})
    assert response.status_code == 422
