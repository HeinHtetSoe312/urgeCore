"""Request/response contracts for crowdfunding. Identity never comes from the body."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Rate = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    target_amount: Money
    target_interest_rate: Rate  # the borrower's maximum rate, in percent


class ContributionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: int = Field(ge=1)
    amount: Money
    lender_yield_bid: Rate


class CampaignRead(BaseModel):
    id: int
    creator_id: int
    title: str
    target_amount: Decimal
    current_raised: Decimal
    target_interest_rate: Decimal
    vwar: Decimal | None
    status: str
    settlement_deadline: datetime | None


class ContributionRead(BaseModel):
    contribution_id: int
    campaign_id: int
    requested_amount: Decimal
    accepted_amount: Decimal
    partially_filled: bool
    lender_yield_bid: Decimal
    campaign_status: str
    current_raised: Decimal
    vwar: Decimal | None
