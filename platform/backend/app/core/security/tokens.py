"""Opaque refresh tokens. The raw token is handed to the browser once (as
an httpOnly, SameSite=strict cookie) and never stored server-side —
only its SHA-256 hash is kept in `core.refresh_token`, so a database
leak alone can't be used to forge sessions. Rotated on every use.
"""
from __future__ import annotations

import hashlib
import secrets


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
