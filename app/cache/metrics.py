"""Cache hit/miss counters.

Kept in a single Redis hash so the numbers survive API restarts and are
shared across replicas. Exposed by ``GET /v1/stats`` -- this is what backs
the hit-rate figure quoted in the README.
"""

from __future__ import annotations

from redis.asyncio import Redis

TIERS = ("place", "near", "list")
_HASH = "metrics:cache"


async def record_hit(cache: Redis, tier: str) -> None:
    await cache.hincrby(_HASH, f"{tier}:hit", 1)


async def record_miss(cache: Redis, tier: str) -> None:
    await cache.hincrby(_HASH, f"{tier}:miss", 1)


async def record_superset_capped(cache: Redis) -> None:
    """A proximity superset hit ``near_superset_cap``.

    Results stay correct but may be truncated; a non-zero count here means
    the cap (or the geohash precision) needs revisiting.
    """
    await cache.hincrby(_HASH, "near:capped", 1)


async def snapshot(cache: Redis) -> dict:
    raw = await cache.hgetall(_HASH) or {}
    counts = {k: int(v) for k, v in raw.items()}

    tiers = {}
    total_hits = total_misses = 0
    for tier in TIERS:
        hits = counts.get(f"{tier}:hit", 0)
        misses = counts.get(f"{tier}:miss", 0)
        total = hits + misses
        tiers[tier] = {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 4) if total else None,
        }
        total_hits += hits
        total_misses += misses

    overall = total_hits + total_misses
    return {
        "tiers": tiers,
        "overall": {
            "hits": total_hits,
            "misses": total_misses,
            "hit_rate": round(total_hits / overall, 4) if overall else None,
        },
        "proximity_supersets_capped": counts.get("near:capped", 0),
    }


async def reset(cache: Redis) -> None:
    await cache.delete(_HASH)
