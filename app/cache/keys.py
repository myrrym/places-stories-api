"""Cache key construction.

Proximity queries carry continuous coordinates, so hashing the raw floats
would make every request a miss. Two quantisations fix that:

1. The query point is snapped to a geohash cell (precision configurable,
   default 6 -- about 1.2 km x 0.6 km).
2. The radius is snapped up to the next bucket in ``radius_buckets_m``.

The database is then queried from the *cell centre* with
``bucket + cell_half_diagonal`` metres, which provably covers every real
query point inside the cell. The service layer re-filters that superset
against the caller's exact coordinates, so the response is still exact --
the quantisation only widens what gets cached, it never changes the answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.geo import geohash_center, geohash_encode, geohash_half_diagonal_m


@dataclass(frozen=True)
class ProximityKey:
    key: str
    geohash: str
    center_lat: float
    center_lon: float
    bucket_m: int
    padded_radius_m: float


def radius_bucket(radius_m: float, settings: Settings) -> int:
    """Snap a radius up to the next configured bucket."""
    capped = min(radius_m, settings.max_radius_m)
    for bucket in sorted(settings.radius_buckets_m):
        if capped <= bucket:
            return bucket
    return settings.max_radius_m


def proximity_key(lat: float, lon: float, radius_m: float, settings: Settings) -> ProximityKey:
    geohash = geohash_encode(lat, lon, settings.geohash_precision)
    bucket = radius_bucket(radius_m, settings)
    center_lat, center_lon = geohash_center(geohash)
    padded = bucket + geohash_half_diagonal_m(geohash)
    return ProximityKey(
        key=f"near:{settings.cache_version}:{geohash}:{bucket}",
        geohash=geohash,
        center_lat=center_lat,
        center_lon=center_lon,
        bucket_m=bucket,
        padded_radius_m=padded,
    )


def place_key(place_id: str, settings: Settings) -> str:
    return f"place:{settings.cache_version}:{place_id}"


def list_key(category: str | None, limit: int, offset: int, settings: Settings) -> str:
    return f"list:{settings.cache_version}:{category or 'all'}:{limit}:{offset}"
