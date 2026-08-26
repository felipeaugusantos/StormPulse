"""hCaptcha verification (anti-abuse, FASE 8).

Optional by design — `Settings.hcaptcha_secret_key` unset means captcha is
not required at all (dev/test convenience, mirrors how VAPID/NDVI/satellite
credentials are all optional elsewhere in this app). Configured, every
`/auth/register` and `/auth/login` call must include a valid `captcha_token`
or gets rejected before touching the database.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings

_VERIFY_URL = "https://hcaptcha.com/siteverify"
_TIMEOUT_SECONDS = 10.0


async def verify_captcha(
    token: str | None,
    settings: Settings,
    *,
    remote_ip: str | None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """True if the captcha is not required (unconfigured) or the token
    actually verified with hCaptcha. False for a missing/invalid/expired
    token, or if hCaptcha's own API is unreachable — a network hiccup on
    their end must never silently let abuse through.

    `client` is injectable (same DI pattern as the weather providers,
    e.g. `InmetWeatherProvider`) so tests can pass an `httpx.MockTransport`
    instead of monkeypatching `httpx.AsyncClient` globally — real callers
    never pass it, a fresh short-lived client is created per call.
    """
    if settings.hcaptcha_secret_key is None:
        return True
    if not token:
        return False

    data = {
        "secret": settings.hcaptcha_secret_key.get_secret_value(),
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        resp = await client.post(_VERIFY_URL, data=data)
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError:
        return False
    finally:
        if owns_client:
            await client.aclose()
    return bool(body.get("success") is True)
