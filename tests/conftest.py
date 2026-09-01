"""Test fixtures.

The geospatial and cache behaviour under test is behaviour of PostGIS and
Redis, so these are integration tests against real services -- mocking them
would only test the mocks. ``docker compose up -d db cache`` (or the
services block in CI) is the prerequisite; see the Makefile ``test`` target.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Point the app at the test services before anything imports app.config,
# whose settings are cached on first read.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://places:places@localhost:55432/places_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/1")
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["RATE_LIMIT_PER_DAY"] = "100000"

# Everything below imports lazily, inside the fixtures. The data-file
# validation tests are the contribution gate and must run with nothing
# installed beyond PyYAML, jsonschema and pytest.

METRES_PER_DEGREE_LAT = 111_195.0

# One cluster in George Town plus a distant place, at distances chosen to sit
# either side of the 500 m and 1000 m radius buckets.
ORIGIN_LAT, ORIGIN_LON = 5.4141, 100.3288

FIXTURE_PLACES = [
    ("alpha", 0.0, "historic"),
    ("bravo", 400.0, "religious"),
    ("charlie", 900.0, "museum"),
    ("delta", 3000.0, "market"),
]


def _offset_north(metres: float) -> tuple[float, float]:
    return ORIGIN_LAT + metres / METRES_PER_DEGREE_LAT, ORIGIN_LON


async def _reset_schema() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings
    from app.db.models import Base

    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _seed() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Category, Place, Story

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for place_id, distance, category in FIXTURE_PLACES:
            lat, lon = _offset_north(distance)
            session.add(
                Place(
                    id=place_id,
                    name=place_id.title(),
                    category=Category(category),
                    geom=f"SRID=4326;POINT({lon} {lat})",
                    city="George Town",
                    state="Penang",
                )
            )
        # Far away: Kuala Lumpur. Must never appear in a Penang query.
        session.add(
            Place(
                id="echo",
                name="Echo",
                category=Category.landmark,
                geom="SRID=4326;POINT(101.6869 3.139)",
                city="Kuala Lumpur",
                state="Kuala Lumpur",
            )
        )
        session.add(
            Story(
                place_id="alpha",
                position=0,
                title="Alpha",
                body_md="A story about Alpha.",
                lang="en",
                source_name="Wikipedia",
                source_url="https://en.wikipedia.org/wiki/Alpha",
                license="CC BY-SA 4.0",
                match_method="manual",
                match_confidence=1.0,
            )
        )
        await session.commit()
    await engine.dispose()


@pytest.fixture(scope="session")
def database() -> None:
    """Create the schema and load fixture places once per test session.

    Deliberately *not* autouse: the data-file validation tests are the
    contribution gate and must run with no services at all.
    """
    asyncio.run(_reset_schema())
    asyncio.run(_seed())


@pytest.fixture
async def session(database):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
async def cache():
    from redis.asyncio import from_url

    from app.config import get_settings

    client = from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def settings():
    from app.config import get_settings

    return get_settings()


@pytest.fixture
async def api_client(database, cache):
    """An httpx client bound to the ASGI app, with startup wiring done by hand."""
    import httpx

    from app.cache.client import close_cache, init_cache
    from app.db.session import dispose_engine, init_engine
    from app.main import app

    init_engine()
    await init_cache()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await close_cache()
    await dispose_engine()
