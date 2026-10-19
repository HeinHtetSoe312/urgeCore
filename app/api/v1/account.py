"""Account endpoints. /me/ledger is added in Week 2 with the ledger service."""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.domain_models import User
from app.schemas.auth import UserPublic

router = APIRouter(tags=["account"])


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
