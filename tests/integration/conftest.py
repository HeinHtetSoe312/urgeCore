"""Fixtures shared by the integration tests (they sit on top of tests/conftest.py)."""

import itertools
from collections.abc import Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token
from app.models.domain_models import User
from app.services import ledger_service


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def make_user(session_factory) -> Callable[[], Awaitable[User]]:
    """Insert a user directly (fast: no argon2). Starts with the default 100.00 balance."""
    counter = itertools.count(1)

    async def _make() -> User:
        async with session_factory() as session:
            user = User(username=f"user{next(counter)}", password_hash="not-a-real-hash")
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    return _make


@pytest.fixture
def auth() -> Callable[[User], dict[str, str]]:
    def _auth(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return _auth


@pytest_asyncio.fixture
async def make_campaign(client, auth):
    async def _make(creator: User, target: str = "100.00", max_rate: str = "12.00") -> dict:
        response = await client.post(
            "/api/v1/crowdfund",
            json={
                "title": "Test campaign",
                "target_amount": target,
                "target_interest_rate": max_rate,
            },
            headers=auth(creator),
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest_asyncio.fixture
async def contribute(client, auth):
    async def _contribute(lender: User, campaign_id: int, amount: str, bid: str = "5.00"):
        return await client.post(
            "/api/v1/crowdfund/contribute",
            json={"campaign_id": campaign_id, "amount": amount, "lender_yield_bid": bid},
            headers=auth(lender),
        )

    return _contribute


@pytest_asyncio.fixture
async def assert_invariants(session_factory):
    """Fails the test (with the offending lines) if I1, I2 or I3 is violated."""

    async def _check() -> None:
        async with session_factory() as session:
            problems = await ledger_service.find_invariant_violations(session)
        assert problems == [], problems

    return _check
