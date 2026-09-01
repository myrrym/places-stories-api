"""Load ``data/places/*.yaml`` into the database.

Idempotent: run it as many times as you like. Every file is validated
against ``data/schema/place.schema.json`` first, so a malformed
contribution fails loudly here (and in CI) rather than half-loading.

    python -m ingestion.load [--dry-run] [--data-dir PATH]

Stories are replaced wholesale per place rather than diffed. They are small,
they always arrive as a complete set from the source file, and wholesale
replacement means a removed story actually disappears.

After a successful write the place's Tier A cache entry is dropped so the
API serves the new version immediately. Tier B proximity keys hold only IDs
and are left to expire.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Category, MatchMethod, Place, Story
from ingestion.validate import DATA_DIR, ValidationFailure, read_records

logger = logging.getLogger("load")


def _parse_date(value) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


async def _upsert(session: AsyncSession, record: dict) -> bool:
    """Write one place and its stories. Returns True if anything changed."""
    place_id = record["id"]
    existing = (
        await session.execute(select(Place).where(Place.id == place_id))
    ).scalar_one_or_none()

    place = existing or Place(id=place_id)
    place.name = record["name"]
    place.name_local = record.get("name_local")
    place.category = Category(record["category"])
    # EWKT is the simplest way to hand a point to a geography column.
    place.geom = f"SRID=4326;POINT({record['lon']} {record['lat']})"
    place.address = record.get("address")
    place.city = record.get("city")
    place.state = record.get("state")
    place.osm_type = record.get("osm_type")
    place.osm_id = record.get("osm_id")
    place.wikidata_id = record.get("wikidata_id")

    if existing is None:
        session.add(place)
        await session.flush()

    await session.execute(delete(Story).where(Story.place_id == place_id))
    for position, story in enumerate(record.get("stories") or []):
        session.add(
            Story(
                place_id=place_id,
                position=position,
                title=story["title"],
                body_md=story["body_md"],
                lang=story.get("lang", "en"),
                source_name=story["source_name"],
                source_url=story["source_url"],
                license=story["license"],
                retrieved_at=_parse_date(story.get("retrieved_at")),
                match_method=MatchMethod(story["match_method"]),
                match_confidence=float(story.get("match_confidence", 1.0)),
            )
        )
    return True


async def load(data_dir: Path = DATA_DIR, dry_run: bool = False) -> dict:
    records = read_records(data_dir)
    summary = {
        "files": len(records),
        "stories": sum(len(r.get("stories") or []) for r in records),
        "story_less": sum(1 for r in records if not r.get("stories")),
        "written": 0,
    }
    if dry_run:
        return summary

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            for record in records:
                await _upsert(session, record)
                summary["written"] += 1
            await session.commit()
    finally:
        await engine.dispose()

    await _invalidate([r["id"] for r in records], settings)
    return summary


async def _invalidate(place_ids: list[str], settings) -> None:
    """Drop Tier A entries for everything we just wrote.

    Best effort: a cache that is down must not fail an ingestion run, and the
    entries expire on their own anyway.
    """
    from redis.asyncio import from_url

    from app.cache.keys import place_key

    cache = from_url(settings.redis_url, decode_responses=True)
    try:
        if place_ids:
            await cache.delete(*[place_key(pid, settings) for pid in place_ids])
    except Exception:
        logger.warning("cache invalidation skipped (cache unreachable)", exc_info=True)
    finally:
        await cache.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not write.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        summary = asyncio.run(load(args.data_dir, dry_run=args.dry_run))
    except ValidationFailure as exc:
        print("Place data failed validation:\n", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1

    print(
        f"files:      {summary['files']}\n"
        f"stories:    {summary['stories']}\n"
        f"story-less: {summary['story_less']}\n"
        f"written:    {summary['written']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
