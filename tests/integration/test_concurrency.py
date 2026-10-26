"""Concurrent money movement: no lost updates, no overfunding, no deadlocks."""

import asyncio
from collections import Counter
from decimal import Decimal

from sqlalchemy import func, select

from app.models.domain_models import (
    CrowdfundCampaign,
    CrowdfundContribution,
    LedgerEntry,
    User,
)

TIMEOUT = 60  # seconds; a deadlock or a stuck lock fails the test instead of hanging CI


async def test_50_concurrent_contributions_fill_the_campaign_exactly(
    make_user, make_campaign, contribute, session_factory, assert_invariants
):
    creator = await make_user()
    lenders = [await make_user() for _ in range(50)]
    campaign = await make_campaign(creator, target="205.00", max_rate="12.00")
    bids = [f"{4 + i % 5}.00" for i in range(50)]  # 4.00 .. 8.00

    jobs = [
        contribute(lender, campaign["id"], "10.00", bids[i]) for i, lender in enumerate(lenders)
    ]
    responses = await asyncio.wait_for(asyncio.gather(*jobs), timeout=TIMEOUT)

    # 20 full fills + 1 partial fill of 5.00 close the campaign; the other 29 are told no.
    assert Counter(r.status_code for r in responses) == {201: 21, 409: 29}
    bodies = [r.json() for r in responses if r.status_code == 201]
    amounts = sorted(Decimal(b["accepted_amount"]) for b in bodies)
    assert sum(amounts) == Decimal("205.00")
    assert amounts == [Decimal("5.00")] + [Decimal("10.00")] * 20
    assert sum(1 for b in bodies if b["partially_filled"]) == 1

    expected_weighted = sum(
        Decimal(b["accepted_amount"]) * Decimal(b["lender_yield_bid"]) for b in bodies
    )
    async with session_factory() as session:
        row = await session.get(CrowdfundCampaign, campaign["id"])
        assert row.current_raised == Decimal("205.00")
        assert row.status == "pending_settlement"
        assert row.settlement_deadline is not None
        assert row.weighted_yield_sum == expected_weighted
        contributions = (
            await session.execute(select(func.count(CrowdfundContribution.id)))
        ).scalar_one()
        ledger_rows = (await session.execute(select(func.count(LedgerEntry.id)))).scalar_one()
        assert contributions == 21
        assert ledger_rows == 21
    await assert_invariants()


async def test_one_lender_cannot_overspend_with_concurrent_requests(
    make_user, make_campaign, contribute, session_factory, assert_invariants
):
    """10 simultaneous 20.00 contributions from a 100.00 balance: exactly 5 can succeed."""
    creator, lender = await make_user(), await make_user()
    campaign = await make_campaign(creator, target="1000.00")

    responses = await asyncio.wait_for(
        asyncio.gather(*(contribute(lender, campaign["id"], "20.00") for _ in range(10))),
        timeout=TIMEOUT,
    )

    assert Counter(r.status_code for r in responses) == {201: 5, 422: 5}
    async with session_factory() as session:
        assert (await session.get(User, lender.id)).balance == Decimal("0.00")
    await assert_invariants()


async def test_lenders_funding_two_campaigns_at_once_never_deadlock(
    make_user, make_campaign, contribute, assert_invariants
):
    creator_a, creator_b = await make_user(), await make_user()
    lenders = [await make_user() for _ in range(20)]
    campaign_a = await make_campaign(creator_a, target="1000.00")
    campaign_b = await make_campaign(creator_b, target="1000.00")

    jobs = []
    for lender in lenders:
        jobs.append(contribute(lender, campaign_a["id"], "10.00"))
        jobs.append(contribute(lender, campaign_b["id"], "10.00"))
    responses = await asyncio.wait_for(asyncio.gather(*jobs), timeout=TIMEOUT)

    assert Counter(r.status_code for r in responses) == {201: 40}
    await assert_invariants()
