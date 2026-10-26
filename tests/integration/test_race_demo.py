"""Interview artifact: the same workload with and without row locking.

_unsafe_contribute is deliberately WRONG: it reads the campaign without a lock, so
concurrent requests all see the same stale state (a lost update). The asyncio.sleep only
widens the window so the bug shows up every time instead of once in a while.
This file may be deleted without affecting the application.
"""

import asyncio
from decimal import Decimal

from sqlalchemy import func, select

from app.models.domain_models import (
    CrowdfundCampaign,
    CrowdfundContribution,
    LedgerEntry,
    User,
)
from app.services import ledger_service

BID = Decimal("5.00")


async def _unsafe_contribute(factory, campaign_id: int, lender_id: int, amount: Decimal) -> None:
    async with factory() as session:
        campaign = await session.get(CrowdfundCampaign, campaign_id)  # plain read: no lock
        lender = await session.get(User, lender_id)
        await asyncio.sleep(0.3)  # every request now holds the same stale snapshot
        accepted = min(amount, campaign.target_amount - campaign.current_raised)
        contribution = CrowdfundContribution(
            campaign_id=campaign_id, user_id=lender_id, amount=accepted, lender_yield_bid=BID
        )
        session.add(contribution)
        await session.flush()
        lender.balance = lender.balance - accepted
        session.add(
            LedgerEntry(
                user_id=lender_id,
                amount=-accepted,
                entry_type="ESCROW_HOLD",
                reference_type="crowdfund_contribution",
                reference_id=contribution.id,
            )
        )
        campaign.current_raised = campaign.current_raised + accepted
        campaign.weighted_yield_sum = campaign.weighted_yield_sum + accepted * BID
        await session.commit()


async def test_without_locking_the_campaign_is_overfunded_and_counters_are_wrong(
    session_factory, make_user, make_campaign
):
    creator = await make_user()
    lenders = [await make_user() for _ in range(10)]
    campaign = await make_campaign(creator, target="50.00")

    await asyncio.gather(
        *(
            _unsafe_contribute(session_factory, campaign["id"], lender.id, Decimal("10.00"))
            for lender in lenders
        )
    )

    async with session_factory() as session:
        funded = (
            await session.execute(select(func.sum(CrowdfundContribution.amount)))
        ).scalar_one()
        row = await session.get(CrowdfundCampaign, campaign["id"])
        problems = await ledger_service.find_invariant_violations(session)
    assert funded == Decimal("100.00")  # twice the 50.00 target was taken from lenders
    assert row.current_raised == Decimal("10.00")  # ...but the campaign recorded only one write
    assert any(p.startswith("I3") for p in problems)


async def test_with_locking_the_same_workload_stops_exactly_at_the_target(
    make_user, make_campaign, contribute, session_factory, assert_invariants
):
    creator = await make_user()
    lenders = [await make_user() for _ in range(10)]
    campaign = await make_campaign(creator, target="50.00")

    responses = await asyncio.gather(
        *(contribute(lender, campaign["id"], "10.00") for lender in lenders)
    )

    assert sorted(r.status_code for r in responses) == [201] * 5 + [409] * 5
    async with session_factory() as session:
        funded = (
            await session.execute(select(func.sum(CrowdfundContribution.amount)))
        ).scalar_one()
        assert funded == Decimal("50.00")
        assert (await session.get(CrowdfundCampaign, campaign["id"])).current_raised == funded
    await assert_invariants()
