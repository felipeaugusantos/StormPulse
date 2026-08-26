"""Integration test proving no config leaks between two `create_app()`
instances in the same process (hardening ADR-0030) — the exact scenario
`Depends(get_settings)` (a process-wide `lru_cache`) would get wrong, and
`Depends(get_request_settings)` (this app instance's real config) gets
right. Needs real Postgres+Redis — auto-skipped otherwise.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration

_PASSWORD = "supersecret123"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "test",
        "log_json": False,
        "log_level": "WARNING",
        "auth_rate_limit_max": 10_000,
        "default_rate_limit_max": 10_000,
        "public_rate_limit_max": 10_000,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
async def client_a() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(jwt_secret_key="a-secret-at-least-32-bytes-long!"))
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as ac,
    ):
        yield ac


@pytest.fixture
async def client_b() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(jwt_secret_key="a-totally-different-b-secret!!!!"))
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as ac,
    ):
        yield ac


async def _register_and_login(client: AsyncClient) -> str:
    email = f"multi-app-{uuid.uuid4().hex}@example.com"
    resp = await client.post(
        "/api/v1/auth/register", json={"accept_terms": True, "email": email, "password": _PASSWORD}
    )
    assert resp.status_code == 201
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 200
    access_token: str = resp.json()["access_token"]
    return access_token


async def test_a_token_from_one_app_instance_is_rejected_by_another(
    client_a: AsyncClient, client_b: AsyncClient
) -> None:
    token_from_a = await _register_and_login(client_a)

    # A token signed with app A's JWT secret must never validate against
    # app B's — if get_current_user (or anything else) fell back to a
    # process-wide cached Settings, this would wrongly succeed whenever
    # both instances happened to share that cache.
    resp = await client_b.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token_from_a}"}
    )
    assert resp.status_code == 401


async def test_each_app_instance_validates_its_own_tokens_correctly(
    client_a: AsyncClient, client_b: AsyncClient
) -> None:
    token_from_a = await _register_and_login(client_a)
    token_from_b = await _register_and_login(client_b)

    resp_a = await client_a.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token_from_a}"}
    )
    resp_b = await client_b.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token_from_b}"}
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200


class _FakeRedis:
    """Minimal in-memory stand-in for the `incr`/`expire` calls
    `RateLimiter` makes — isolates this test from the real (shared)
    Redis, so two app instances never accidentally share a bucket just
    because a test client's fake `request.client.host` is identical."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def aclose(self) -> None:
        # The app's lifespan teardown calls this on whatever `app.state.redis`
        # currently is — must be a harmless no-op for this fake.
        return None


async def test_auth_rate_limit_does_not_leak_between_app_instances() -> None:
    """A very low auth_rate_limit_max on one instance must not affect a
    sibling instance configured with a high ceiling — proves the auth rate
    limiter (previously built once at import time) now reads *this app's*
    settings per request, not a module-level snapshot."""
    strict_app = create_app(_settings(auth_rate_limit_max=1, jwt_secret_key="strict-app-secret!!"))
    lenient_app = create_app(
        _settings(auth_rate_limit_max=10_000, jwt_secret_key="lenient-app-secret!")
    )

    async with (
        strict_app.router.lifespan_context(strict_app),
        lenient_app.router.lifespan_context(lenient_app),
        AsyncClient(
            transport=ASGITransport(app=strict_app), base_url="http://testserver"
        ) as strict_client,
        AsyncClient(
            transport=ASGITransport(app=lenient_app), base_url="http://testserver"
        ) as lenient_client,
    ):
        # Each app gets its own fake Redis bucket — isolates this test from
        # whether the real limiter key happens to collide across instances
        # (a separate, legitimate concern for Fase 8 / proxy-aware keys),
        # keeping this one focused purely on "which max_requests applies".
        strict_app.state.redis = _FakeRedis()
        lenient_app.state.redis = _FakeRedis()

        # Exhaust the strict app's auth rate limit (max_requests=1).
        email = f"multi-app-rl-{uuid.uuid4().hex}@example.com"
        first = await strict_client.post(
            "/api/v1/auth/register",
            json={"accept_terms": True, "email": email, "password": _PASSWORD},
        )
        assert first.status_code == 201
        second = await strict_client.post(
            "/api/v1/auth/register",
            json={"email": f"{email}.2", "password": _PASSWORD, "accept_terms": True},
        )
        assert second.status_code == 429

        # The lenient app, with its own high ceiling, is unaffected — proves
        # the limiter reads *this app's* settings, not a shared/cached one.
        for i in range(5):
            resp = await lenient_client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"multi-app-rl-{uuid.uuid4().hex}@example.com",
                    "password": _PASSWORD,
                    "accept_terms": True,
                },
            )
            assert resp.status_code == 201, f"request {i} unexpectedly rate-limited"
