"""Crowdfunding: create campaigns and contribute with pessimistic row locking.

Lock order for contribute: the campaign row first, then the lender's user
row. Every read that decides something is FOR UPDATE + populate_existing.
Settlement (accept, refunds) is not built yet.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.domain_models import CrowdfundCampaign, CrowdfundContribution
from app.services import ledger_service
from app.services.vwar_service import compute_vwar


class CampaignNotFoundError(Exception):
    """No campaign with that id."""


class CampaignNotActiveError(Exception):
    """The campaign is full or closed and accepts no more contributions."""


class CreatorCannotContributeError(Exception):
    """A creator may not fund their own campaign."""


class BidAboveTargetError(Exception):
    """The lender's yield bid is above the borrower's maximum rate."""


@dataclass(frozen=True)
class ContributionResult:
    contribution_id: int
    campaign_id: int
    requested_amount: Decimal
    accepted_amount: Decimal
    lender_yield_bid: Decimal
    campaign_status: str
    current_raised: Decimal
    vwar: Decimal | None


async def create_campaign(
    session: AsyncSession,
    *,
    creator_id: int,
    title: str,
    target_amount: Decimal,
    target_interest_rate: Decimal,
) -> CrowdfundCampaign:
    campaign = CrowdfundCampaign(
        creator_id=creator_id,
        title=title,
        target_amount=target_amount,
        target_interest_rate=target_interest_rate,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)  # load every column (async sessions cannot lazy-load)
    return campaign


async def lock_campaign(session: AsyncSession, campaign_id: int) -> CrowdfundCampaign | None:
    stmt = (
        select(CrowdfundCampaign)
        .where(CrowdfundCampaign.id == campaign_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def contribute(
    session: AsyncSession,
    *,
    campaign_id: int,
    lender_id: int,
    amount: Decimal,
    bid: Decimal,
) -> ContributionResult:
    """Escrow `amount` (or whatever still fits) from the lender into the campaign.

    One transaction. Any failure rolls back, which also releases the row locks.
    """
    try:
        return await _contribute(
            session, campaign_id=campaign_id, lender_id=lender_id, amount=amount, bid=bid
        )
    except Exception:
        await session.rollback()
        raise


async def _contribute(
    session: AsyncSession,
    *,
    campaign_id: int,
    lender_id: int,
    amount: Decimal,
    bid: Decimal,
) -> ContributionResult:
    # 1. Parent row first. Concurrent contributors queue here, one at a time.
    campaign = await lock_campaign(session, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(campaign_id)
    if campaign.creator_id == lender_id:
        raise CreatorCannotContributeError(campaign_id)
    if campaign.status != "active":
        raise CampaignNotActiveError(campaign_id)
    if bid > campaign.target_interest_rate:
        raise BidAboveTargetError(campaign_id)

    # 2. Partial fill: take only what still fits. Safe because we hold the campaign lock.
    remaining = campaign.target_amount - campaign.current_raised
    accepted = min(amount, remaining)

    # 3. Then the user row, with fresh values.
    lender = await ledger_service.lock_user(session, lender_id)

    contribution = CrowdfundContribution(
        campaign_id=campaign.id,
        user_id=lender_id,
        amount=accepted,
        lender_yield_bid=bid,
        status="held",
    )
    session.add(contribution)
    await session.flush()  # assigns contribution.id for the ledger reference

    await ledger_service.post_entry(
        session,
        lender,
        -accepted,
        "ESCROW_HOLD",
        "crowdfund_contribution",
        contribution.id,
    )

    campaign.current_raised = campaign.current_raised + accepted
    campaign.weighted_yield_sum = campaign.weighted_yield_sum + accepted * bid
    if campaign.current_raised == campaign.target_amount:
        window = timedelta(seconds=get_settings().settlement_window_seconds)
        campaign.status = "pending_settlement"
        campaign.settlement_deadline = datetime.now(UTC) + window

    await session.commit()
    return ContributionResult(
        contribution_id=contribution.id,
        campaign_id=campaign.id,
        requested_amount=amount,
        accepted_amount=accepted,
        lender_yield_bid=bid,
        campaign_status=campaign.status,
        current_raised=campaign.current_raised,
        vwar=compute_vwar(campaign.weighted_yield_sum, campaign.current_raised),
    )
