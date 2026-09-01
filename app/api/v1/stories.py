"""Story endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from app.deps import CacheDep, SessionDep, SettingsDep
from app.schemas.places import StoriesResponse
from app.services import places as service

router = APIRouter(prefix="/places", tags=["stories"])


@router.get(
    "/{place_id}/stories",
    response_model=StoriesResponse,
    summary="Stories for a place",
    description=(
        "Each story carries mandatory attribution and the confidence with which "
        "it was matched to this place. A place with no confident match returns an "
        "empty list rather than a wrong story."
    ),
)
async def place_stories(
    session: SessionDep,
    cache: CacheDep,
    settings: SettingsDep,
    place_id: str = Path(...),
) -> StoriesResponse:
    payload = await service.get_place_payload(session, cache, settings, place_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No place with id {place_id!r}.")
    stories = payload["stories"]
    return StoriesResponse(place_id=place_id, count=len(stories), results=stories)
