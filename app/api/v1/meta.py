"""Health and observability endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.cache import metrics
from app.db.repositories import places as repo
from app.deps import CacheDep, SessionDep, SettingsDep

router = APIRouter(tags=["meta"])


@router.get("/stats", summary="Cache hit rate and dataset size")
async def stats(session: SessionDep, cache: CacheDep, settings: SettingsDep) -> dict:
    """Live cache counters. This is what backs the hit-rate figure in the README."""
    return {
        "cache": await metrics.snapshot(cache),
        "cache_config": {
            "version": settings.cache_version,
            "geohash_precision": settings.geohash_precision,
            "radius_buckets_m": settings.radius_buckets_m,
            "place_ttl_seconds": settings.place_ttl_seconds,
            "near_ttl_seconds": settings.near_ttl_seconds,
        },
        "dataset": {
            "places": await repo.count_places(session),
            "stories": await repo.count_stories(session),
        },
    }
