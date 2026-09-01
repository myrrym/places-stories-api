"""Place endpoints: proximity search, single fetch, browse."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query

from app.db.models import Category
from app.deps import CacheDep, SessionDep, SettingsDep
from app.schemas.places import (
    NearbyQuery,
    NearbyResponse,
    PlaceListResponse,
    PlaceOut,
)
from app.services import places as service

router = APIRouter(prefix="/places", tags=["places"])


@router.get(
    "/near",
    response_model=NearbyResponse,
    summary="Places near a point",
    description=(
        "Proximity search using PostGIS `ST_DWithin` on a geography column: "
        "true spherical distance in metres, ordered nearest first."
    ),
)
async def places_near(
    session: SessionDep,
    cache: CacheDep,
    settings: SettingsDep,
    lat: float = Query(..., ge=-90, le=90, examples=[5.4141]),
    lon: float = Query(..., ge=-180, le=180, examples=[100.3288]),
    radius_m: int = Query(1000, ge=1, description="Search radius in metres."),
    limit: int | None = Query(None, ge=1, description="Max results to return."),
) -> NearbyResponse:
    if radius_m > settings.max_radius_m:
        raise HTTPException(
            status_code=422,
            detail=f"radius_m must not exceed {settings.max_radius_m}.",
        )
    effective_limit = min(limit or settings.default_limit, settings.max_limit)

    results, truncated = await service.find_nearby(
        session, cache, settings, lat, lon, radius_m, effective_limit
    )
    return NearbyResponse(
        query=NearbyQuery(
            lat=lat, lon=lon, radius_m=radius_m, limit=effective_limit, truncated=truncated
        ),
        count=len(results),
        results=results,
    )


@router.get("", response_model=PlaceListResponse, summary="Browse places")
async def list_places(
    session: SessionDep,
    cache: CacheDep,
    settings: SettingsDep,
    category: Category | None = Query(None),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
) -> PlaceListResponse:
    effective_limit = min(limit or settings.default_limit, settings.max_limit)
    results, total = await service.list_places(
        session, cache, settings, category, effective_limit, offset
    )
    return PlaceListResponse(
        count=len(results),
        total=total,
        limit=effective_limit,
        offset=offset,
        category=category,
        results=results,
    )


@router.get("/{place_id}", response_model=PlaceOut, summary="Fetch one place with its stories")
async def get_place(
    session: SessionDep,
    cache: CacheDep,
    settings: SettingsDep,
    place_id: str = Path(..., examples=["khoo-kongsi"]),
) -> PlaceOut:
    payload = await service.get_place_payload(session, cache, settings, place_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No place with id {place_id!r}.")
    return PlaceOut(**payload)
