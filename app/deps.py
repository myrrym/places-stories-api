"""FastAPI dependency wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.client import get_cache
from app.config import Settings, get_settings
from app.db.session import get_session


async def session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def cache_dep() -> Redis:
    return get_cache()


def settings_dep() -> Settings:
    return get_settings()


SessionDep = Annotated[AsyncSession, Depends(session_dep)]
CacheDep = Annotated[Redis, Depends(cache_dep)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
