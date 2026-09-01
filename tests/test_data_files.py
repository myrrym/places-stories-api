"""Contribution gate.

This is the test that guards ``data/places/``. It needs no database and no
network, so a contributor -- and CI -- gets a fast, precise answer on whether
a submitted place file is valid.
"""

from __future__ import annotations

import pytest

from ingestion.load import DATA_DIR, ValidationFailure, read_records


@pytest.fixture(scope="module")
def records():
    try:
        return read_records(DATA_DIR)
    except ValidationFailure as exc:
        pytest.fail(f"data/places contains invalid files:\n{exc}")


def test_dataset_is_not_empty(records):
    assert len(records) > 0


def test_every_place_has_coordinates_inside_malaysia(records):
    """A sanity fence. Wrong hemisphere is the classic lat/lon swap symptom."""
    for record in records:
        assert 0.5 <= record["lat"] <= 7.5, record["id"]
        assert 99.0 <= record["lon"] <= 120.0, record["id"]


def test_every_story_carries_attribution(records):
    """Non-negotiable: no story ships without a source, URL and licence."""
    for record in records:
        for story in record.get("stories") or []:
            assert story["source_name"], record["id"]
            assert story["source_url"].startswith("http"), record["id"]
            assert story["license"], record["id"]


def test_geosearch_matches_meet_the_confidence_threshold(records):
    """Fail-closed matching: a low-confidence story should never have shipped."""
    from ingestion.match import MIN_NAME_SIMILARITY

    for record in records:
        for story in record.get("stories") or []:
            if story["match_method"] == "geosearch":
                assert story.get("match_confidence", 0) >= MIN_NAME_SIMILARITY, record["id"]


def test_ids_are_unique(records):
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))
