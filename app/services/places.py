"""Cache-aside orchestration between the API layer and PostGIS.

Two cache tiers, and they are deliberately different shapes:

* **Tier A, per place** (``place:<ver>:<id>``) holds the full serialised
  place with its stories. Long TTL, invalidated explicitly on write.
  This is where the hit rate comes from.
* **Tier B, per proximity query** (``near:<ver>:<geohash>:<bucket>``) holds
  *only* place IDs and coordinates. Short TTL. Results are hydrated through
  Tier A, so story text is never duplicated across geo keys and a place
  edit does not require hunting down geo keys to invalidate.
"""

from __future__ import annotations

import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import metrics
from app.cache.keys import list_key, place_key, proximity_key
from app.config import Settings
from app.db.models import Category
from app.db.repositories import places as repo
from app.geo import haversine_m


def serialize_place(record: repo.PlaceRecord) -> dict:
    place = record.place
    return {
        "id": place.id,
        "name": place.name,
        "name_local": place.name_local,
        "category": place.category.value,
        "lat": record.lat,
        "lon": record.lon,
        "address": place.address,
        "city": place.city,
        "state": place.state,
        "sources": {
            "osm_type": place.osm_type,
            "osm_id": place.osm_id,
            "wikidata_id": place.wikidata_id,
        },
        "story_count": len(place.stories),
        "stories": [
            {
                "title": s.title,
                "body_md": s.body_md,
                "lang": s.lang,
                "attribution": {
                    "source_name": s.source_name,
                    "source_url": s.source_url,
                    "license": s.license,
                    "retrieved_at": s.retrieved_at.isoformat() if s.retrieved_at else None,
                },
                "match": {
                    "method": s.match_method.value,
                    "confidence": s.match_confidence,
                },
            }
            for s in place.stories
        ],
    }


async def get_place_payloads(
    session: AsyncSession,
    cache: Redis,
    settings: Settings,
    place_ids: list[str],
) -> dict[str, dict]:
    """Tier A read-through for a batch of places, order preserved by caller."""
    if not place_ids:
        return {}

    keys = [place_key(pid, settings) for pid in place_ids]
    cached = await cache.mget(keys)

    payloads: dict[str, dict] = {}
    missing: list[str] = []
    for pid, raw in zip(place_ids, cached, strict=True):
        if raw:
            payloads[pid] = json.loads(raw)
            await metrics.record_hit(cache, "place")
        else:
            missing.append(pid)
            await metrics.record_miss(cache, "place")

    if missing:
        records = await repo.get_places(session, missing)
        pipe = cache.pipeline()
        for pid, record in records.items():
            payload = serialize_place(record)
            payloads[pid] = payload
            pipe.set(place_key(pid, settings), json.dumps(payload), ex=settings.place_ttl_seconds)
        await pipe.execute()

    return payloads


async def get_place_payload(
    session: AsyncSession, cache: Redis, settings: Settings, place_id: str
) -> dict | None:
    payloads = await get_place_payloads(session, cache, settings, [place_id])
    return payloads.get(place_id)


async def find_nearby(
    session: AsyncSession,
    cache: Redis,
    settings: Settings,
    lat: float,
    lon: float,
    radius_m: int,
    limit: int,
) -> tuple[list[dict], bool]:
    """Proximity search, exact results, quantised cache key.

    The cached superset is queried from the geohash cell *centre* with
    ``bucket + cell_half_diagonal`` metres. For any real query point inside
    the cell, every place within ``bucket`` of it is provably inside that
    padded circle -- so the cache holds a superset, and the exact filter
    below restores an exact answer for the caller's true coordinates.
    """
    pkey = proximity_key(lat, lon, radius_m, settings)

    raw = await cache.get(pkey.key)
    if raw is not None:
        await metrics.record_hit(cache, "near")
        cached = json.loads(raw)
        superset = [repo.NearRow(**row) for row in cached["rows"]]
        truncated = cached["truncated"]
    else:
        await metrics.record_miss(cache, "near")
        superset, truncated = await repo.find_within_radius(
            session,
            pkey.center_lat,
            pkey.center_lon,
            pkey.padded_radius_m,
            settings.near_superset_cap,
        )
        if truncated:
            await metrics.record_superset_capped(cache)
        await cache.set(
            pkey.key,
            json.dumps(
                {
                    "rows": [{"id": r.id, "lat": r.lat, "lon": r.lon} for r in superset],
                    "truncated": truncated,
                }
            ),
            ex=settings.near_ttl_seconds,
        )

    # Exact re-filter against the caller's real coordinates and real radius.
    scored = [(haversine_m(lat, lon, row.lat, row.lon), row.id) for row in superset]
    within = sorted((d, pid) for d, pid in scored if d <= radius_m)[:limit]

    ordered_ids = [pid for _, pid in within]
    payloads = await get_place_payloads(session, cache, settings, ordered_ids)

    results = []
    for distance, pid in within:
        payload = payloads.get(pid)
        if payload is None:
            # Cached geo row points at a place that has since been deleted.
            continue
        results.append({**payload, "distance_m": round(distance, 1)})

    return results, truncated


async def list_places(
    session: AsyncSession,
    cache: Redis,
    settings: Settings,
    category: Category | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    key = list_key(category.value if category else None, limit, offset, settings)

    raw = await cache.get(key)
    if raw is not None:
        await metrics.record_hit(cache, "list")
        cached = json.loads(raw)
        ids, total = cached["ids"], cached["total"]
    else:
        await metrics.record_miss(cache, "list")
        ids = await repo.list_place_ids(session, category, limit, offset)
        total = await repo.count_places(session, category)
        await cache.set(key, json.dumps({"ids": ids, "total": total}), ex=settings.list_ttl_seconds)

    payloads = await get_place_payloads(session, cache, settings, ids)
    return [payloads[pid] for pid in ids if pid in payloads], total


async def invalidate_place(cache: Redis, settings: Settings, place_id: str) -> None:
    """Drop a place from Tier A. Called by the ingestion loader after a write.

    Tier B geo keys are left to expire on their own -- they hold only IDs, so
    a stale one costs at most one extra hydration, never stale story text.
    """
    await cache.delete(place_key(place_id, settings))
