"""Ledger service: the only code allowed to change a user's balance.

Rules every caller follows:
1. Lock rows in the global order: the parent row first (a campaign), then user rows,
   in ascending user_id when there is more than one.
2. Lock a user with lock_user(): SELECT ... FOR UPDATE plus populate_existing.
3. Change a balance only with post_entry(), which writes the ledger row in the same
   transaction as the balance change.

Invariants (checked by find_invariant_violations and by the tests):
  I1  for every user: balance == 100.00 + SUM(that user's ledger amounts)
  I2  money is conserved: SUM(balances) + SUM(held contributions) == 100.00 * users
  I3  for every campaign: current_raised and weighted_yield_sum equal the sums over
      its held/released contributions
"""

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain_models import (
    CrowdfundCampaign,
    CrowdfundContribution,
    LedgerEntry,
    User,
)

STARTING_BALANCE = Decimal("100.00")
CENT = Decimal("0.01")


class UserNotFoundError(Exception):
    """The user row does not exist."""


class InsufficientFundsError(Exception):
    """The posting would make the balance negative."""


async def lock_user(session: AsyncSession, user_id: int) -> User:
    """Lock one user row and return it with FRESH attribute values.

    populate_existing matters: get_current_user already loaded this User into the
    request's session, and without it the ORM would return that cached object with a
    possibly stale balance instead of the values read under the lock.
    """
    stmt = (
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(user_id)
    return user


async def post_entry(
    session: AsyncSession,
    user: User,
    amount: Decimal,
    entry_type: str,
    reference_type: str,
    reference_id: int,
) -> LedgerEntry:
    """Apply one signed amount to a LOCKED user and append the matching ledger row.

    The caller must already hold the row lock (lock_user). Nothing is committed here.
    """
    if amount == 0 or amount != amount.quantize(CENT):
        raise ValueError("amount must be non-zero with at most 2 decimal places")
    new_balance = user.balance + amount
    if new_balance < 0:
        raise InsufficientFundsError(f"balance {user.balance} cannot cover {amount}")
    user.balance = new_balance
    entry = LedgerEntry(
        user_id=user.id,
        amount=amount,
        entry_type=entry_type,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    session.add(entry)
    return entry


async def find_invariant_violations(session: AsyncSession) -> list[str]:
    """Return a human-readable line per violated invariant (empty list = all good)."""
    problems: list[str] = []

    # I1: balance == 100.00 + SUM(ledger)
    totals = (
        select(LedgerEntry.user_id.label("user_id"), func.sum(LedgerEntry.amount).label("total"))
        .group_by(LedgerEntry.user_id)
        .subquery()
    )
    expected = func.coalesce(totals.c.total, 0) + STARTING_BALANCE
    rows = await session.execute(
        select(User.id, User.balance, expected.label("expected"))
        .outerjoin(totals, totals.c.user_id == User.id)
        .where(User.balance != expected)
        .order_by(User.id)
    )
    for user_id, balance, expected_balance in rows:
        problems.append(f"I1: user {user_id} balance {balance} != expected {expected_balance}")

    # I2: SUM(balances) + SUM(held contributions) == 100.00 * number of users
    total_balance = (
        await session.execute(select(func.coalesce(func.sum(User.balance), 0)))
    ).scalar_one()
    user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    held = (
        await session.execute(
            select(func.coalesce(func.sum(CrowdfundContribution.amount), 0)).where(
                CrowdfundContribution.status == "held"
            )
        )
    ).scalar_one()
    if Decimal(total_balance) + Decimal(held) != STARTING_BALANCE * user_count:
        problems.append(
            f"I2: balances {total_balance} + held {held} != {STARTING_BALANCE * user_count}"
        )

    # I3: campaign counters match their contributions
    contributions = (
        select(
            CrowdfundContribution.campaign_id.label("campaign_id"),
            func.sum(CrowdfundContribution.amount).label("raised"),
            func.sum(CrowdfundContribution.amount * CrowdfundContribution.lender_yield_bid).label(
                "weighted"
            ),
        )
        .where(CrowdfundContribution.status.in_(("held", "released")))
        .group_by(CrowdfundContribution.campaign_id)
        .subquery()
    )
    raised = func.coalesce(contributions.c.raised, 0)
    weighted = func.coalesce(contributions.c.weighted, 0)
    rows = await session.execute(
        select(CrowdfundCampaign.id, CrowdfundCampaign.current_raised, raised.label("raised"))
        .outerjoin(contributions, contributions.c.campaign_id == CrowdfundCampaign.id)
        .where(
            or_(
                CrowdfundCampaign.current_raised != raised,
                CrowdfundCampaign.weighted_yield_sum != weighted,
            )
        )
        .order_by(CrowdfundCampaign.id)
    )
    for campaign_id, current_raised, actual in rows:
        problems.append(
            f"I3: campaign {campaign_id} current_raised {current_raised} != contributions {actual}"
        )
    return problems
