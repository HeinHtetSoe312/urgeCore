"""Account endpoints: the caller's profile."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.domain_models import LedgerEntry, User
from app.schemas.auth import UserPublic
from app.schemas.ledger import LedgerEntryRead

router = APIRouter(tags=["account"])


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/me/ledger", response_model=list[LedgerEntryRead])
async def my_ledger(
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LedgerEntry]:
    # Authorization is in the query itself: only rows owned by the caller can match.
    stmt = select(LedgerEntry).where(LedgerEntry.user_id == current_user.id)
    if before_id is not None:
        stmt = stmt.where(LedgerEntry.id < before_id)
    stmt = stmt.order_by(LedgerEntry.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())
