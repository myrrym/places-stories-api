"""Geospatial layer: the quantisation maths, and the PostGIS query itself."""

from __future__ import annotations

import pytest

from app.db.repositories import places as repo
from app.geo import (
    geohash_bbox,
    geohash_center,
    geohash_encode,
    geohash_half_diagonal_m,
    haversine_m,
)
from tests.conftest import ORIGIN_LAT, ORIGIN_LON, _offset_north


def test_geohash_encode_is_stable_and_prefixed():
    full = geohash_encode(ORIGIN_LAT, ORIGIN_LON, 9)
    assert geohash_encode(ORIGIN_LAT, ORIGIN_LON, 6) == full[:6]


def test_geohash_bbox_contains_its_point():
    geohash = geohash_encode(ORIGIN_LAT, ORIGIN_LON, 6)
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(geohash)
    assert lat_min <= ORIGIN_LAT <= lat_max
    assert lon_min <= ORIGIN_LON <= lon_max


def test_half_diagonal_covers_every_point_in_the_cell():
    """The padding guarantee the proximity cache depends on.

    If this fails, a cached superset can miss a place that a real query
    inside the cell should have found.
    """
    geohash = geohash_encode(ORIGIN_LAT, ORIGIN_LON, 6)
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(geohash)
    center_lat, center_lon = geohash_center(geohash)
    half_diagonal = geohash_half_diagonal_m(geohash)

    for lat in (lat_min, lat_max, (lat_min + lat_max) / 2):
        for lon in (lon_min, lon_max, (lon_min + lon_max) / 2):
            assert haversine_m(center_lat, center_lon, lat, lon) <= half_diagonal + 1e-6


def test_haversine_matches_known_offsets():
    lat, lon = _offset_north(400.0)
    assert haversine_m(ORIGIN_LAT, ORIGIN_LON, lat, lon) == pytest.approx(400, abs=2)


async def test_within_radius_excludes_places_outside_it(session):
    rows, truncated = await repo.find_within_radius(session, ORIGIN_LAT, ORIGIN_LON, 500, 50)
    assert [r.id for r in rows] == ["alpha", "bravo"]
    assert truncated is False


async def test_within_radius_is_ordered_nearest_first(session):
    rows, _ = await repo.find_within_radius(session, ORIGIN_LAT, ORIGIN_LON, 1000, 50)
    assert [r.id for r in rows] == ["alpha", "bravo", "charlie"]


async def test_within_radius_never_returns_another_city(session):
    rows, _ = await repo.find_within_radius(session, ORIGIN_LAT, ORIGIN_LON, 50_000, 50)
    assert "echo" not in {r.id for r in rows}


async def test_truncation_is_reported(session):
    rows, truncated = await repo.find_within_radius(session, ORIGIN_LAT, ORIGIN_LON, 1000, 2)
    assert len(rows) == 2
    assert truncated is True


async def test_coordinates_round_trip_through_the_geography_column(session):
    record = await repo.get_place(session, "bravo")
    expected_lat, expected_lon = _offset_north(400.0)
    assert record is not None
    assert record.lat == pytest.approx(expected_lat, abs=1e-6)
    assert record.lon == pytest.approx(expected_lon, abs=1e-6)
