"""End-to-end checks through the ASGI app."""

from __future__ import annotations

from tests.conftest import ORIGIN_LAT, ORIGIN_LON


async def test_health(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_places_near(api_client):
    response = await api_client.get(
        "/v1/places/near", params={"lat": ORIGIN_LAT, "lon": ORIGIN_LON, "radius_m": 1000}
    )
    assert response.status_code == 200
    body = response.json()
    assert [r["id"] for r in body["results"]] == ["alpha", "bravo", "charlie"]
    assert body["query"]["radius_m"] == 1000


async def test_places_near_rejects_an_oversized_radius(api_client, settings):
    response = await api_client.get(
        "/v1/places/near",
        params={"lat": ORIGIN_LAT, "lon": ORIGIN_LON, "radius_m": settings.max_radius_m + 1},
    )
    assert response.status_code == 422


async def test_get_place_with_stories(api_client):
    response = await api_client.get("/v1/places/alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["story_count"] == 1
    story = body["stories"][0]
    assert story["attribution"]["license"] == "CC BY-SA 4.0"
    assert story["match"]["confidence"] == 1.0


async def test_get_missing_place_is_404(api_client):
    assert (await api_client.get("/v1/places/nope")).status_code == 404


async def test_place_stories_endpoint(api_client):
    response = await api_client.get("/v1/places/alpha/stories")
    assert response.status_code == 200
    assert response.json()["count"] == 1


async def test_story_less_place_returns_an_empty_list_not_an_error(api_client):
    """A place with no confident source match is a valid place, not a failure."""
    response = await api_client.get("/v1/places/bravo/stories")
    assert response.status_code == 200
    assert response.json()["results"] == []


async def test_browse_and_filter_by_category(api_client):
    response = await api_client.get("/v1/places", params={"category": "museum"})
    assert response.status_code == 200
    body = response.json()
    assert [r["id"] for r in body["results"]] == ["charlie"]
    assert body["total"] == 1


async def test_stats_exposes_hit_rate(api_client):
    await api_client.get(
        "/v1/places/near", params={"lat": ORIGIN_LAT, "lon": ORIGIN_LON, "radius_m": 1000}
    )
    body = (await api_client.get("/v1/stats")).json()
    assert "hit_rate" in body["cache"]["overall"]
    assert body["dataset"]["places"] >= 5


async def test_rate_limit_headers_present(api_client):
    response = await api_client.get("/v1/places", params={"limit": 1})
    assert "X-RateLimit-Limit" in response.headers
