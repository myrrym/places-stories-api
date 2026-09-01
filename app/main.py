"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import meta, places, stories
from app.cache.client import close_cache, get_cache, init_cache
from app.config import get_settings
from app.db.session import dispose_engine, init_engine
from app.middleware.ratelimit import RateLimitMiddleware

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    await init_cache()
    yield
    await close_cache()
    await dispose_engine()


app = FastAPI(
    title="Places & Stories API",
    version="0.1.0",
    summary="Open, geospatial API for Malaysian landmarks and the stories behind them.",
    description=(
        "Ask what is near you and get places back with their histories. Coordinates "
        "come from OpenStreetMap; narratives come from Wikipedia. Every story ships "
        "with its source, licence and match confidence.\n\n"
        "Source: https://github.com/myrrym/places-stories-api"
    ),
    lifespan=lifespan,
    root_path=settings.api_root_path,
)

app.add_middleware(RateLimitMiddleware, cache_getter=get_cache, settings=settings)

app.include_router(places.router, prefix="/v1")
app.include_router(stories.router, prefix="/v1")
app.include_router(meta.router, prefix="/v1")


@app.get("/health", tags=["meta"], summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "version": app.version}
