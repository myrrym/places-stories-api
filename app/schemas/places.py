"""Public response models. These are the API contract."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.db.models import Category, MatchMethod


class Attribution(BaseModel):
    """Where a story came from. Required on every story, no exceptions."""

    source_name: str = Field(examples=["Wikipedia"])
    source_url: str
    license: str = Field(examples=["CC BY-SA 4.0"])
    retrieved_at: date | None = None


class StoryMatch(BaseModel):
    """How confidently this story was linked to this place."""

    method: MatchMethod
    confidence: float = Field(ge=0, le=1)


class StoryOut(BaseModel):
    title: str
    body_md: str
    lang: str
    attribution: Attribution
    match: StoryMatch


class PlaceSources(BaseModel):
    osm_type: str | None = None
    osm_id: int | None = None
    wikidata_id: str | None = None


class PlaceOut(BaseModel):
    id: str
    name: str
    name_local: str | None = None
    category: Category
    lat: float
    lon: float
    address: str | None = None
    city: str | None = None
    state: str | None = None
    sources: PlaceSources
    story_count: int
    stories: list[StoryOut]


class NearbyPlaceOut(PlaceOut):
    distance_m: float = Field(description="Great-circle distance from the query point, in metres.")


class NearbyResponse(BaseModel):
    query: NearbyQuery
    count: int
    results: list[NearbyPlaceOut]


class NearbyQuery(BaseModel):
    lat: float
    lon: float
    radius_m: int
    limit: int
    truncated: bool = Field(
        default=False,
        description=(
            "True when the underlying proximity superset hit its cap and results "
            "may be incomplete. Narrow the radius."
        ),
    )


class PlaceListResponse(BaseModel):
    count: int
    total: int
    limit: int
    offset: int
    category: Category | None = None
    results: list[PlaceOut]


class StoriesResponse(BaseModel):
    place_id: str
    count: int
    results: list[StoryOut]


NearbyResponse.model_rebuild()
