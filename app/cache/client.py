"""Redis connection handling."""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.config import get_settings

_client: Redis | None = None


async def init_cache() -> Redis:
    global _client
    if _client is None:
        _client = from_url(get_settings().redis_url, decode_responses=True)
    return _client


def get_cache() -> Redis:
    if _client is None:  # pragma: no cover - wiring guard
        raise RuntimeError("cache not initialised; call init_cache() on startup")
    return _client


async def close_cache() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
