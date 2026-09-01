"""Application settings, loaded from environment or a local .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = "postgresql+asyncpg://places:places@db:5432/places"
    redis_url: str = "redis://cache:6379/0"

    # Cache. Bumping cache_version invalidates every cached key at once.
    cache_version: str = "v1"
    place_ttl_seconds: int = 86_400
    near_ttl_seconds: int = 600
    list_ttl_seconds: int = 600

    # Proximity-query quantisation. Precision 6 is roughly a 1.2 km x 0.6 km cell.
    geohash_precision: int = 6
    radius_buckets_m: list[int] = [500, 1000, 2000, 5000, 10_000, 25_000]
    max_radius_m: int = 50_000
    # Hard cap on how many places a single cached proximity superset may hold.
    near_superset_cap: int = 500

    default_limit: int = 20
    max_limit: int = 100

    # Rate limiting, per client IP.
    rate_limit_per_minute: int = 60
    rate_limit_per_day: int = 1000
    trusted_proxy_cidrs: list[str] = []

    log_level: str = "INFO"
    api_root_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
