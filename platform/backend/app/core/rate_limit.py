"""General API rate limiting — one `Limiter` shared across the whole app,
backed by Redis (not slowapi's in-memory default) so limits survive a
process restart and stay correct if this app is ever run as more than one
worker. `slowapi` was already a listed dependency before this — it just
wasn't wired up anywhere; this is that wiring.

`limiter.limit(...)` is applied explicitly to the WhatsApp webhook (the one
truly unauthenticated route in the app) and to `profiles`' public
registration/invite routes; every other route gets `rate_limit_default`
automatically via `default_limits`. Disabled in tests via
`settings.rate_limit_enabled=False` (see conftest) so a burst of
assertions across many test functions sharing one TestClient host doesn't
trip the limiter and cause unrelated flakiness.
"""
from __future__ import annotations

from slowapi import Limiter

from app.config import settings
from app.core.security.dependencies import client_ip

limiter = Limiter(
    key_func=client_ip,
    storage_uri=settings.redis_url,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
)
