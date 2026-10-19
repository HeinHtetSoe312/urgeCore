"""Redis client lifecycle."""

import redis.asyncio as aioredis

_client: aioredis.Redis | None = None


def init_redis(url: str) -> None:
    global _client
    _client = aioredis.from_url(url, decode_responses=True)


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def get_redis() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis client is not initialised")
    return _client
