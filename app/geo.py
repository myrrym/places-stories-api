"""Pure geospatial helpers used by the cache layer.

The database does the real proximity work (PostGIS ``ST_DWithin`` on a
``geography`` column). These functions exist only so a continuous
lat/lon pair can be *quantised* into a stable cache key, and so the
superset returned by a quantised query can be re-filtered against the
caller's exact coordinates.
"""

from __future__ import annotations

import math

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
EARTH_RADIUS_M = 6_371_008.8


def geohash_encode(lat: float, lon: float, precision: int) -> str:
    """Encode a point as a geohash of ``precision`` characters."""
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    bits = (16, 8, 4, 2, 1)
    bit = 0
    ch = 0
    even = True
    out: list[str] = []

    while len(out) < precision:
        if even:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if lon > mid:
                ch |= bits[bit]
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if lat > mid:
                ch |= bits[bit]
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_BASE32[ch])
            bit = 0
            ch = 0

    return "".join(out)


def geohash_bbox(geohash: str) -> tuple[float, float, float, float]:
    """Return ``(lat_min, lat_max, lon_min, lon_max)`` for a geohash cell."""
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    even = True

    for char in geohash:
        try:
            idx = _BASE32.index(char)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"invalid geohash character: {char!r}") from exc
        for mask in (16, 8, 4, 2, 1):
            interval = lon_interval if even else lat_interval
            mid = (interval[0] + interval[1]) / 2
            if idx & mask:
                interval[0] = mid
            else:
                interval[1] = mid
            even = not even

    return lat_interval[0], lat_interval[1], lon_interval[0], lon_interval[1]


def geohash_center(geohash: str) -> tuple[float, float]:
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(geohash)
    return (lat_min + lat_max) / 2, (lon_min + lon_max) / 2


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def geohash_half_diagonal_m(geohash: str) -> float:
    """Max distance from a cell's centre to any point inside the cell.

    This is the padding added to a cached proximity query's radius so the
    cached result is guaranteed to be a superset for every real query
    point that lands in the cell.
    """
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(geohash)
    lat_c, lon_c = (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
    # The far corner is the widest one; at these latitudes the difference
    # between corners is centimetres, but take the max and stay honest.
    return max(
        haversine_m(lat_c, lon_c, lat, lon)
        for lat in (lat_min, lat_max)
        for lon in (lon_min, lon_max)
    )
