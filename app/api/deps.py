"""Shared FastAPI dependencies. Authorization rule: identity ONLY comes from the token."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemDetail
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db
from app.models.domain_models import User

bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized() -> ProblemDetail:
    return ProblemDetail(
        status=401,
        title="Unauthorized",
        detail="Missing or invalid credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise unauthorized() from None
    user = await db.get(User, user_id)
    if user is None:
        raise unauthorized()
    return user
