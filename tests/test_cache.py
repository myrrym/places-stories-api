"""Cache layer: key quantisation, hit/miss behaviour, and exactness.

The interesting property is that quantising the cache key must not change
the answer. These tests pin that down.
"""

from __future__ import annotations

from app.cache import metrics
from app.cache.keys import proximity_key, radius_bucket
from app.services import places as service
from tests.conftest import ORIGIN_LAT, ORIGIN_LON


def test_radius_snaps_up_to_the_next_bucket(settings):
    assert radius_bucket(1, settings) == 500
    assert radius_bucket(500, settings) == 500
    assert radius_bucket(501, settings) == 1000
    assert radius_bucket(999_999, settings) == settings.max_radius_m


def test_near_duplicate_coordinates_share_one_key(settings):
    """The whole point of quantisation: a 10 m nudge is not a new cache entry."""
    a = proximity_key(ORIGIN_LAT, ORIGIN_LON, 1000, settings)
    b = proximity_key(ORIGIN_LAT + 0.00009, ORIGIN_LON + 0.00009, 1000, settings)
    assert a.key == b.key


def test_padded_radius_exceeds_the_requested_bucket(settings):
    key = proximity_key(ORIGIN_LAT, ORIGIN_LON, 1000, settings)
    assert key.padded_radius_m > key.bucket_m


async def test_second_identical_query_is_a_cache_hit(session, cache, settings):
    await service.find_nearby(session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 1000, 20)
    first = await metrics.snapshot(cache)
    assert first["tiers"]["near"]["misses"] == 1

    await service.find_nearby(session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 1000, 20)
    second = await metrics.snapshot(cache)
    assert second["tiers"]["near"]["hits"] == 1
    assert second["tiers"]["near"]["misses"] == 1


async def test_nearby_coordinates_hit_the_same_cached_superset(session, cache, settings):
    await service.find_nearby(session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 1000, 20)
    await service.find_nearby(session, cache, settings, ORIGIN_LAT + 0.00009, ORIGIN_LON, 1000, 20)
    snapshot = await metrics.snapshot(cache)
    assert snapshot["tiers"]["near"]["hits"] == 1


async def test_quantised_cache_still_returns_exact_results(session, cache, settings):
    """A place inside the padded superset but outside the real radius is dropped.

    ``charlie`` sits 900 m out. A 500 m query snaps to the 500 m bucket and a
    padded superset of roughly 1.2 km, so charlie *is* in the cached superset
    -- and must still be filtered out of the response.
    """
    results, _ = await service.find_nearby(
        session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 500, 20
    )
    assert [r["id"] for r in results] == ["alpha", "bravo"]

    # Same cached superset, wider real radius: charlie reappears.
    results, _ = await service.find_nearby(
        session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 1000, 20
    )
    assert [r["id"] for r in results] == ["alpha", "bravo", "charlie"]


async def test_results_carry_exact_distance_not_cell_centre_distance(session, cache, settings):
    results, _ = await service.find_nearby(
        session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 1000, 20
    )
    by_id = {r["id"]: r for r in results}
    assert by_id["alpha"]["distance_m"] < 1.0
    assert 395 < by_id["bravo"]["distance_m"] < 405


async def test_place_tier_is_populated_and_reused(session, cache, settings):
    await service.get_place_payload(session, cache, settings, "alpha")
    after_first = await metrics.snapshot(cache)
    assert after_first["tiers"]["place"]["misses"] == 1

    payload = await service.get_place_payload(session, cache, settings, "alpha")
    after_second = await metrics.snapshot(cache)
    assert after_second["tiers"]["place"]["hits"] == 1
    assert payload["stories"][0]["attribution"]["source_name"] == "Wikipedia"


async def test_invalidating_a_place_forces_a_reread(session, cache, settings):
    await service.get_place_payload(session, cache, settings, "alpha")
    await service.invalidate_place(cache, settings, "alpha")
    await metrics.reset(cache)

    await service.get_place_payload(session, cache, settings, "alpha")
    snapshot = await metrics.snapshot(cache)
    assert snapshot["tiers"]["place"]["misses"] == 1


async def test_stories_hydrate_through_the_place_tier(session, cache, settings):
    """Proximity results carry stories without the geo key ever storing them."""
    results, _ = await service.find_nearby(
        session, cache, settings, ORIGIN_LAT, ORIGIN_LON, 500, 20
    )
    alpha = next(r for r in results if r["id"] == "alpha")
    assert alpha["story_count"] == 1

    key = proximity_key(ORIGIN_LAT, ORIGIN_LON, 500, settings).key
    raw = await cache.get(key)
    assert "A story about Alpha" not in raw
