from decimal import Decimal

import pytest


async def test_create_campaign(client, make_user, make_campaign):
    creator = await make_user()
    campaign = await make_campaign(creator, target="100.00", max_rate="12.00")
    assert campaign["creator_id"] == creator.id
    assert campaign["status"] == "active"
    assert campaign["current_raised"] == "0.00"
    assert campaign["vwar"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "x", "target_amount": "-5.00", "target_interest_rate": "5.00"},
        {"title": "x", "target_amount": "0.00", "target_interest_rate": "5.00"},
        {"title": "x", "target_amount": "10.005", "target_interest_rate": "5.00"},
        {"title": "x", "target_amount": "10.00", "target_interest_rate": "100.01"},
        {"title": "", "target_amount": "10.00", "target_interest_rate": "5.00"},
        {"target_amount": "10.00", "target_interest_rate": "5.00"},
        {"title": "x", "target_amount": "10.00", "target_interest_rate": "5.00", "creator_id": 1},
    ],
)
async def test_create_campaign_rejects_invalid_input(client, make_user, auth, payload):
    creator = await make_user()
    response = await client.post("/api/v1/crowdfund", json=payload, headers=auth(creator))
    assert response.status_code == 422


async def test_contribute_updates_campaign_vwar_balance_and_ledger(
    client, make_user, make_campaign, contribute, auth, assert_invariants
):
    creator, lender1, lender2 = await make_user(), await make_user(), await make_user()
    campaign = await make_campaign(creator, target="500.00")

    first = await contribute(lender1, campaign["id"], "100.00", "5.00")
    second = await contribute(lender2, campaign["id"], "50.00", "8.00")
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["partially_filled"] is False

    state = (await client.get(f"/api/v1/crowdfund/{campaign['id']}", headers=auth(creator))).json()
    assert state["current_raised"] == "150.00"
    assert state["vwar"] == "6.00"  # (100*5 + 50*8) / 150
    assert state["status"] == "active"

    me = (await client.get("/api/v1/me", headers=auth(lender1))).json()
    assert me["balance"] == "0.00"
    ledger = (await client.get("/api/v1/me/ledger", headers=auth(lender1))).json()
    assert [(e["amount"], e["entry_type"]) for e in ledger] == [("-100.00", "ESCROW_HOLD")]
    await assert_invariants()


async def test_partial_fill_then_campaign_closes(
    client, make_user, make_campaign, contribute, auth, assert_invariants
):
    creator, lender1, lender2, lender3 = [await make_user() for _ in range(4)]
    campaign = await make_campaign(creator, target="60.00")

    assert (await contribute(lender1, campaign["id"], "40.00")).status_code == 201
    partial = await contribute(lender2, campaign["id"], "50.00")
    body = partial.json()
    assert partial.status_code == 201, partial.text
    assert body["accepted_amount"] == "20.00"
    assert body["partially_filled"] is True
    assert body["campaign_status"] == "pending_settlement"

    me = (await client.get("/api/v1/me", headers=auth(lender2))).json()
    assert me["balance"] == "80.00"  # only the accepted 20.00 was taken
    late = await contribute(lender3, campaign["id"], "10.00")
    assert late.status_code == 409
    await assert_invariants()


async def test_bid_above_the_campaign_maximum_is_rejected(make_user, make_campaign, contribute):
    creator, lender = await make_user(), await make_user()
    campaign = await make_campaign(creator, max_rate="12.00")
    response = await contribute(lender, campaign["id"], "10.00", "12.01")
    assert response.status_code == 422


async def test_creator_cannot_fund_their_own_campaign(make_user, make_campaign, contribute):
    creator = await make_user()
    campaign = await make_campaign(creator)
    assert (await contribute(creator, campaign["id"], "10.00")).status_code == 403


async def test_insufficient_funds_changes_nothing(
    client, make_user, make_campaign, contribute, auth, assert_invariants
):
    creator, lender = await make_user(), await make_user()
    campaign = await make_campaign(creator, target="500.00")
    response = await contribute(lender, campaign["id"], "150.00")
    assert response.status_code == 422

    assert (await client.get("/api/v1/me", headers=auth(lender))).json()["balance"] == "100.00"
    assert (await client.get("/api/v1/me/ledger", headers=auth(lender))).json() == []
    state = (await client.get(f"/api/v1/crowdfund/{campaign['id']}", headers=auth(creator))).json()
    assert Decimal(state["current_raised"]) == Decimal("0.00")
    await assert_invariants()


async def test_unknown_campaign_is_404(client, make_user, contribute, auth):
    lender = await make_user()
    assert (await contribute(lender, 999999, "10.00")).status_code == 404
    response = await client.get("/api/v1/crowdfund/999999", headers=auth(lender))
    assert response.status_code == 404


async def test_list_shows_only_active_campaigns(client, make_user, make_campaign, contribute, auth):
    creator, lender = await make_user(), await make_user()
    open_campaign = await make_campaign(creator, target="100.00")
    full_campaign = await make_campaign(creator, target="10.00")
    await contribute(lender, full_campaign["id"], "10.00")

    listing = (await client.get("/api/v1/crowdfund", headers=auth(lender))).json()
    assert [c["id"] for c in listing] == [open_campaign["id"]]
