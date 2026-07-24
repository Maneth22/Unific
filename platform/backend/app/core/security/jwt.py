"""Short-lived JWT access tokens. Refresh tokens are handled separately in
`tokens.py` — they are opaque, stored hashed, and revocable, whereas an
access token is stateless by design and simply expires (~15 min per the
plan) so no revocation list is needed for it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from jwt import InvalidTokenError

from app.config import settings

TokenAudience = Literal["staff", "client", "client_staff"]


def create_access_token(subject: str, audience: TokenAudience, extra_claims: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, audience: TokenAudience) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=audience,
        )
    except InvalidTokenError:
        return None
