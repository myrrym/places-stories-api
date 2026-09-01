"""Every geospatial query in the project lives in this module.

Nothing else may write PostGIS SQL. Keeping ``ST_DWithin`` in one file is
what makes the geospatial layer testable in isolation and swappable later.
"""

from __future__ import annotations

from dataclasses import dataclass

from geoalchemy2 import Geometry
from sqlalchemy import Select, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Place, Story


@dataclass(frozen=True)
class NearRow:
    """The minimum a proximity query needs to return.

    Deliberately not the full place: proximity results are cached as ID +
    coordinates only, then hydrated through the per-place cache. That keeps
    story text out of the geo cache and makes invalidation cheap.
    """

    id: str
    lat: float
    lon: float


_NEAR_SQL = text(
    """
    SELECT id,
           ST_Y(geom::geometry) AS lat,
           ST_X(geom::geometry) AS lon
    FROM places
    WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
    ORDER BY ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
    LIMIT :limit
    """
)


async def find_within_radius(
    session: AsyncSession,
    lat: float,
    lon: float,
    radius_m: float,
    limit: int,
) -> tuple[list[NearRow], bool]:
    """Places whose point is within ``radius_m`` metres, nearest first.

    ``ST_DWithin`` on a ``geography`` column is a true spherical distance in
    metres and is index-assisted by the GiST index on ``places.geom`` -- no
    projection maths, no bounding-box approximation, no cell-boundary cases.

    Returns ``(rows, truncated)``. ``truncated`` is True when the result hit
    ``limit``, meaning more places may exist in range.
    """
    result = await session.execute(
        _NEAR_SQL, {"lat": lat, "lon": lon, "radius": radius_m, "limit": limit}
    )
    rows = [NearRow(id=r.id, lat=r.lat, lon=r.lon) for r in result]
    return rows, len(rows) >= limit


def _list_stmt(category: Category | None) -> Select:
    stmt = select(Place.id).order_by(Place.name)
    if category is not None:
        stmt = stmt.where(Place.category == category)
    return stmt


async def list_place_ids(
    session: AsyncSession,
    category: Category | None,
    limit: int,
    offset: int,
) -> list[str]:
    result = await session.execute(_list_stmt(category).limit(limit).offset(offset))
    return list(result.scalars())


async def count_places(session: AsyncSession, category: Category | None = None) -> int:
    stmt = select(func.count(Place.id))
    if category is not None:
        stmt = stmt.where(Place.category == category)
    return int((await session.execute(stmt)).scalar_one())


async def count_stories(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(Story.id)))).scalar_one())


# ``geom`` is a geography column; cast to geometry to pull raw lat/lon back
# out. Selected alongside the ORM entity so hydration is a single round trip.
_LAT = func.ST_Y(cast(Place.geom, Geometry)).label("lat")
_LON = func.ST_X(cast(Place.geom, Geometry)).label("lon")


@dataclass(frozen=True)
class PlaceRecord:
    """A place plus its decoded coordinates, ready for serialisation."""

    place: Place
    lat: float
    lon: float


async def get_place(session: AsyncSession, place_id: str) -> PlaceRecord | None:
    result = await session.execute(select(Place, _LAT, _LON).where(Place.id == place_id))
    row = result.first()
    return PlaceRecord(place=row[0], lat=row.lat, lon=row.lon) if row else None


async def get_places(session: AsyncSession, place_ids: list[str]) -> dict[str, PlaceRecord]:
    if not place_ids:
        return {}
    result = await session.execute(select(Place, _LAT, _LON).where(Place.id.in_(place_ids)))
    return {row[0].id: PlaceRecord(place=row[0], lat=row.lat, lon=row.lon) for row in result}
