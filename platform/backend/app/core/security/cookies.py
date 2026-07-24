"""Consistent handling of the refresh-token cookie — httpOnly, SameSite
strict, Secure in production — so every login flow (staff, client) sets/
clears it identically. `path` is scoped narrowly to the specific refresh
endpoint each audience uses, not shared broadly: the browser only attaches
a cookie to requests whose path starts with the cookie's `path`, so a
cookie set with the wrong path is silently never sent — this is exactly
the bug that shipped in Phase C's first cut (staff's `/api/auth` path was
reused for the client login, whose refresh endpoint lives under
`/api/profiles/client`, outside that scope) and was caught during the
Phase E frontend build before it ever reached a browser.
"""
from __future__ import annotations

from fastapi import Response

from app.config import settings

REFRESH_COOKIE_NAME = "unific_refresh"

STAFF_COOKIE_PATH = "/api/auth"
CLIENT_COOKIE_PATH = "/api/profiles/client"
CLIENT_STAFF_COOKIE_PATH = "/api/profiles/client-staff"


def set_refresh_cookie(response: Response, raw_token: str, max_age_seconds: int, path: str = STAFF_COOKIE_PATH) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path=path,
    )


def clear_refresh_cookie(response: Response, path: str = STAFF_COOKIE_PATH) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=path)
