"""Object-level authorization: identity only ever comes from the token."""

import pytest

from app.core.security import create_access_token

CAMPAIGN = {"title": "x", "target_amount": "10.00", "target_interest_rate": "5.00"}
CONTRIBUTION = {"campaign_id": 1, "amount": "1.00", "lender_yield_bid": "5.00"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/crowdfund", None),
        ("GET", "/api/v1/crowdfund/1", None),
        ("POST", "/api/v1/crowdfund", CAMPAIGN),
        ("POST", "/api/v1/crowdfund/contribute", CONTRIBUTION),
        ("GET", "/api/v1/me/ledger", None),
    ],
)
async def test_every_money_route_requires_a_token(client, method, path, body):
    response = await client.request(method, path, json=body)
    assert response.status_code == 401


async def test_token_for_a_user_that_does_not_exist_is_rejected(client):
    headers = {"Authorization": f"Bearer {create_access_token(999999)}"}
    assert (await client.get("/api/v1/me/ledger", headers=headers)).status_code == 401


async def test_a_user_only_sees_their_own_ledger(
    client, make_user, make_campaign, contribute, auth
):
    creator, alice, bob = await make_user(), await make_user(), await make_user()
    campaign = await make_campaign(creator, target="500.00")
    await contribute(alice, campaign["id"], "30.00")

    alice_ledger = (await client.get("/api/v1/me/ledger", headers=auth(alice))).json()
    bob_ledger = (await client.get("/api/v1/me/ledger", headers=auth(bob))).json()
    assert len(alice_ledger) == 1
    assert bob_ledger == []


async def test_the_body_cannot_name_another_user(client, make_user, make_campaign, auth):
    creator, alice, bob = await make_user(), await make_user(), await make_user()
    campaign = await make_campaign(creator, target="500.00")
    spoofed = {**CONTRIBUTION, "campaign_id": campaign["id"], "user_id": bob.id}
    response = await client.post("/api/v1/crowdfund/contribute", json=spoofed, headers=auth(alice))
    assert response.status_code == 422  # extra fields are forbidden
    assert (await client.get("/api/v1/me/ledger", headers=auth(bob))).json() == []


async def test_a_campaign_always_belongs_to_the_caller(client, make_user, auth):
    alice, bob = await make_user(), await make_user()
    response = await client.post("/api/v1/crowdfund", json=CAMPAIGN, headers=auth(alice))
    assert response.json()["creator_id"] == alice.id
    assert response.json()["creator_id"] != bob.id
