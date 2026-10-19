"""Kubernetes-style probes. Responses reveal no internal detail."""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemDetail
from app.db.redis import get_redis
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/liveness")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
async def readiness(
    db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        await redis.ping()
    except Exception:
        raise ProblemDetail(503, "Service Unavailable", "A dependency is not ready.") from None
    return {"status": "ready"}
