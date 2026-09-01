"""Per-IP rate limiting backed by Redis.

Fixed-window counters (one minute, one day) incremented by a Lua script so
the increment and its expiry are atomic across replicas. Fixed windows can
allow a 2x burst across a window boundary; that is an accepted trade for v1
simplicity, and a sliding-window log is the documented upgrade.

The limiter fails **open**: if Redis is unreachable the request is served.
An outage in the cache should not take the public API down with it.
"""

from __future__ import annotations

import ipaddress
import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

logger = logging.getLogger(__name__)

# KEYS: minute counter, day counter. ARGV: none needed beyond expiries.
_LUA = """
local m = redis.call('INCR', KEYS[1])
if m == 1 then redis.call('EXPIRE', KEYS[1], 60) end
local d = redis.call('INCR', KEYS[2])
if d == 1 then redis.call('EXPIRE', KEYS[2], 86400) end
return {m, d, redis.call('TTL', KEYS[1]), redis.call('TTL', KEYS[2])}
"""

EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


def client_ip(request: Request, trusted_cidrs: list[str]) -> str:
    """Resolve the client IP.

    ``X-Forwarded-For`` is only believed when the immediate peer is inside a
    configured trusted CIDR. Otherwise anyone could spoof the header and walk
    straight past the limiter.
    """
    peer = request.client.host if request.client else "unknown"
    if not trusted_cidrs:
        return peer

    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer

    trusted = any(peer_addr in ipaddress.ip_network(c, strict=False) for c in trusted_cidrs)
    if not trusted:
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    return forwarded.split(",")[0].strip()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cache_getter, settings: Settings):
        super().__init__(app)
        self._cache_getter = cache_getter
        self._settings = settings
        self._script_sha: str | None = None

    async def _run(self, cache: Redis, minute_key: str, day_key: str):
        if self._script_sha is None:
            self._script_sha = await cache.script_load(_LUA)
        try:
            return await cache.evalsha(self._script_sha, 2, minute_key, day_key)
        except Exception:
            # Script cache flushed (e.g. after a Redis restart); reload once.
            self._script_sha = await cache.script_load(_LUA)
            return await cache.evalsha(self._script_sha, 2, minute_key, day_key)

    async def dispatch(self, request: Request, call_next):
        settings = self._settings
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        ip = client_ip(request, settings.trusted_proxy_cidrs)
        now = int(time.time())
        minute_key = f"rl:{settings.cache_version}:{ip}:m:{now // 60}"
        day_key = f"rl:{settings.cache_version}:{ip}:d:{now // 86400}"

        try:
            cache: Redis = self._cache_getter()
            minute_count, day_count, minute_ttl, day_ttl = await self._run(
                cache, minute_key, day_key
            )
        except Exception:
            logger.warning("rate limiter unavailable, failing open", exc_info=True)
            return await call_next(request)

        over_minute = minute_count > settings.rate_limit_per_minute
        over_day = day_count > settings.rate_limit_per_day

        if over_minute or over_day:
            retry_after = max(1, minute_ttl if over_minute else day_ttl)
            limit = settings.rate_limit_per_minute if over_minute else settings.rate_limit_per_day
            window = "minute" if over_minute else "day"
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded: {limit} requests per {window}.",
                    "window": window,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, settings.rate_limit_per_minute - minute_count)
        )
        response.headers["X-RateLimit-Reset"] = str(max(0, minute_ttl))
        return response
