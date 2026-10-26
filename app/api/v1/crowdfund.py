"""Crowdfunding endpoints. Identity comes from the token only."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import ProblemDetail
from app.db.session import get_db
from app.models.domain_models import CrowdfundCampaign, User
from app.schemas.crowdfund import (
    CampaignCreate,
    CampaignRead,
    ContributionCreate,
    ContributionRead,
)
from app.services import crowdfund_service, ledger_service
from app.services.vwar_service import compute_vwar

router = APIRouter(prefix="/crowdfund", tags=["crowdfund"])


def _to_read(campaign: CrowdfundCampaign) -> CampaignRead:
    return CampaignRead(
        id=campaign.id,
        creator_id=campaign.creator_id,
        title=campaign.title,
        target_amount=campaign.target_amount,
        current_raised=campaign.current_raised,
        target_interest_rate=campaign.target_interest_rate,
        vwar=compute_vwar(campaign.weighted_yield_sum, campaign.current_raised),
        status=campaign.status,
        settlement_deadline=campaign.settlement_deadline,
    )


@router.post("", response_model=CampaignRead, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignRead:
    campaign = await crowdfund_service.create_campaign(
        db,
        creator_id=current_user.id,
        title=body.title,
        target_amount=body.target_amount,
        target_interest_rate=body.target_interest_rate,
    )
    return _to_read(campaign)


@router.post("/contribute", response_model=ContributionRead, status_code=201)
async def contribute(
    body: ContributionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContributionRead:
    try:
        result = await crowdfund_service.contribute(
            db,
            campaign_id=body.campaign_id,
            lender_id=current_user.id,
            amount=body.amount,
            bid=body.lender_yield_bid,
        )
    except crowdfund_service.CampaignNotFoundError:
        raise ProblemDetail(404, "Not Found", "Campaign not found.") from None
    except crowdfund_service.CreatorCannotContributeError:
        raise ProblemDetail(403, "Forbidden", "You cannot fund your own campaign.") from None
    except crowdfund_service.CampaignNotActiveError:
        raise ProblemDetail(
            409, "Conflict", "The campaign is not accepting contributions."
        ) from None
    except crowdfund_service.BidAboveTargetError:
        raise ProblemDetail(
            422, "Unprocessable Entity", "Your bid is above the campaign's maximum rate."
        ) from None
    except ledger_service.InsufficientFundsError:
        raise ProblemDetail(422, "Unprocessable Entity", "Insufficient funds.") from None
    return ContributionRead(
        contribution_id=result.contribution_id,
        campaign_id=result.campaign_id,
        requested_amount=result.requested_amount,
        accepted_amount=result.accepted_amount,
        partially_filled=result.accepted_amount < result.requested_amount,
        lender_yield_bid=result.lender_yield_bid,
        campaign_status=result.campaign_status,
        current_raised=result.current_raised,
        vwar=result.vwar,
    )


@router.get("", response_model=list[CampaignRead])
async def list_active_campaigns(
    limit: int = Query(50, ge=1, le=100),
    after_id: int = Query(0, ge=0),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignRead]:
    stmt = (
        select(CrowdfundCampaign)
        .where(CrowdfundCampaign.status == "active", CrowdfundCampaign.id > after_id)
        .order_by(CrowdfundCampaign.id)
        .limit(limit)
    )
    return [_to_read(c) for c in (await db.execute(stmt)).scalars()]


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign(
    campaign_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignRead:
    campaign = await db.get(CrowdfundCampaign, campaign_id)
    if campaign is None:
        raise ProblemDetail(404, "Not Found", "Campaign not found.")
    return _to_read(campaign)
