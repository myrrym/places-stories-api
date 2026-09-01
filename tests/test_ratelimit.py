"""Rate limiting: the counter, the 429, and the trusted-proxy rule."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.middleware.ratelimit import client_ip


def _request(peer: str, forwarded: str | None = None) -> object:
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers,
        url=SimpleNamespace(path="/v1/places"),
    )


def test_forwarded_header_is_ignored_from_an_untrusted_peer():
    """Otherwise anyone could spoof the header and bypass the limiter."""
    request = _request("203.0.113.9", forwarded="1.2.3.4")
    assert client_ip(request, ["10.0.0.0/8"]) == "203.0.113.9"


def test_forwarded_header_is_trusted_from_a_configured_proxy():
    request = _request("10.1.2.3", forwarded="1.2.3.4, 10.1.2.3")
    assert client_ip(request, ["10.0.0.0/8"]) == "1.2.3.4"


def test_no_trusted_proxies_means_always_use_the_peer():
    request = _request("10.1.2.3", forwarded="1.2.3.4")
    assert client_ip(request, []) == "10.1.2.3"


@pytest.fixture
async def strict_client(database, cache, monkeypatch):
    """An app instance with a deliberately tiny per-minute allowance."""
    from app.cache.client import close_cache, init_cache
    from app.db.session import dispose_engine, init_engine
    from app.main import app

    for middleware in app.user_middleware:
        settings = getattr(middleware, "kwargs", {}).get("settings")
        if settings is not None:
            monkeypatch.setattr(settings, "rate_limit_per_minute", 3, raising=False)

    init_engine()
    await init_cache()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await close_cache()
    await dispose_engine()


async def test_requests_over_the_limit_get_429_with_retry_after(strict_client):
    statuses = []
    for _ in range(5):
        response = await strict_client.get("/v1/places", params={"limit": 1})
        statuses.append(response.status_code)

    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429

    blocked = await strict_client.get("/v1/places", params={"limit": 1})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


async def test_health_is_never_rate_limited(strict_client):
    for _ in range(10):
        assert (await strict_client.get("/health")).status_code == 200
