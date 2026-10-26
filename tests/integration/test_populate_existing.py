"""Why lock_user uses populate_existing: the session's identity map caches rows."""

from decimal import Decimal

from sqlalchemy import select, update

from app.models.domain_models import User


async def _set_balance_in_another_session(session_factory, user_id: int, balance: str) -> None:
    async with session_factory() as writer:
        await writer.execute(
            update(User).where(User.id == user_id).values(balance=Decimal(balance))
        )
        await writer.commit()


async def test_locking_read_with_populate_existing_returns_the_fresh_balance(
    session_factory, make_user
):
    user = await make_user()
    async with session_factory() as reader:
        await reader.get(User, user.id)  # what get_current_user does: caches the row
        await _set_balance_in_another_session(session_factory, user.id, "40.00")

        stmt = (
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        fresh = (await reader.execute(stmt)).scalar_one()
        assert fresh.balance == Decimal("40.00")


async def test_locking_read_without_populate_existing_can_return_the_cached_balance(
    session_factory, make_user
):
    """The pitfall itself. If a future SQLAlchemy changes this behaviour, this test fails
    and the fix is to delete it: the populate_existing test above is the one that matters."""
    user = await make_user()
    async with session_factory() as reader:
        loaded = await reader.get(User, user.id)
        await _set_balance_in_another_session(session_factory, user.id, "40.00")

        stmt = select(User).where(User.id == user.id).with_for_update()
        stale = (await reader.execute(stmt)).scalar_one()
        assert stale is loaded  # same Python object from the identity map
        assert stale.balance == Decimal("100.00")  # the row says 40.00; the cache says 100.00
