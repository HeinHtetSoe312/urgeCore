from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.models.domain_models import LedgerEntry, User
from app.services import ledger_service


async def test_post_entry_changes_balance_and_writes_a_ledger_row(
    session_factory, make_user, assert_invariants
):
    user = await make_user()
    recipient = await make_user()

    async with session_factory() as session:
        locked = await ledger_service.lock_user(session, user.id)
        locked_recipient = await ledger_service.lock_user(session, recipient.id)

        # Ensure entry_type strings strictly match the ck_ledger_entries_entry_type_valid constraint
        await ledger_service.post_entry(session, locked, Decimal("-30.00"), "SPEND", "test", 1)
        await ledger_service.post_entry(
            session, locked_recipient, Decimal("30.00"), "SPEND", "test", 1
        )
        await session.commit()

    async with session_factory() as session:
        assert (await session.get(User, user.id)).balance == Decimal("70.00")
        assert (await session.get(User, recipient.id)).balance == Decimal("130.00")

        entries = (
            (await session.execute(select(LedgerEntry).order_by(LedgerEntry.id))).scalars().all()
        )
        assert [(e.user_id, e.amount) for e in entries] == [
            (user.id, Decimal("-30.00")),
            (recipient.id, Decimal("30.00")),
        ]

    await assert_invariants()


async def test_insufficient_funds_raises_and_writes_nothing(session_factory, make_user):
    user = await make_user()
    async with session_factory() as session:
        locked = await ledger_service.lock_user(session, user.id)
        with pytest.raises(ledger_service.InsufficientFundsError):
            await ledger_service.post_entry(session, locked, Decimal("-100.01"), "SPEND", "test", 1)
        await session.rollback()

    async with session_factory() as session:
        assert (await session.get(User, user.id)).balance == Decimal("100.00")
        assert (await session.execute(select(func.count(LedgerEntry.id)))).scalar_one() == 0


@pytest.mark.parametrize("bad_amount", ["0.00", "1.005"])
async def test_post_entry_rejects_zero_and_sub_cent_amounts(session_factory, make_user, bad_amount):
    user = await make_user()
    async with session_factory() as session:
        locked = await ledger_service.lock_user(session, user.id)
        with pytest.raises(ValueError):
            await ledger_service.post_entry(session, locked, Decimal(bad_amount), "SPEND", "t", 1)


async def test_database_check_constraint_rejects_negative_balance(session_factory, make_user):
    user = await make_user()
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(User).where(User.id == user.id).values(balance=Decimal("-1.00"))
            )
            await session.commit()


async def test_invariant_check_detects_a_balance_changed_outside_the_ledger(
    session_factory, make_user
):
    user = await make_user()
    async with session_factory() as session:  # tampering on purpose: no ledger row
        await session.execute(
            update(User).where(User.id == user.id).values(balance=Decimal("90.00"))
        )
        await session.commit()
    async with session_factory() as session:
        problems = await ledger_service.find_invariant_violations(session)
    assert any(p.startswith("I1") for p in problems)
    assert any(p.startswith("I2") for p in problems)
