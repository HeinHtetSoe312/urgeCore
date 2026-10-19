"""Register and login."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.errors import ProblemDetail
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.domain_models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    # argon2 is CPU-heavy; run it in a thread so the event loop is not blocked.
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = User(username=body.username.lower(), password_hash=password_hash)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ProblemDetail(409, "Conflict", "Username is not available.") from None
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.username == body.username.lower()))
    user = result.scalar_one_or_none()
    # Always run one verification so unknown users and wrong passwords look alike.
    hash_to_check = user.password_hash if user is not None else DUMMY_HASH
    password_ok = await run_in_threadpool(verify_password, body.password, hash_to_check)
    if user is None or not password_ok:
        raise ProblemDetail(
            401,
            "Unauthorized",
            "Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user.id))
