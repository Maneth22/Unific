"""Issues, rotates and revokes refresh tokens; mints access tokens.
Shared by staff and client login flows (client flow lands in Phase C)
so both audiences get identical session-security behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.common import utcnow
from app.core.models.staff import RefreshToken
from app.core.security.jwt import TokenAudience, create_access_token
from app.core.security.tokens import generate_refresh_token, hash_refresh_token


@dataclass
class IssuedTokens:
    access_token: str
    raw_refresh_token: str
    refresh_expires_at_seconds: int


async def issue_tokens(
    db: AsyncSession,
    *,
    audience: TokenAudience,
    staff_user_id: str | None = None,
    client_user_id: str | None = None,
    client_staff_user_id: str | None = None,
) -> IssuedTokens:
    subject = {"staff": staff_user_id, "client": client_user_id, "client_staff": client_staff_user_id}[audience]
    assert subject is not None

    access_token = create_access_token(subject=subject, audience=audience)

    raw_refresh = generate_refresh_token()
    expires_at = utcnow() + timedelta(days=settings.refresh_token_expire_days)
    db.add(
        RefreshToken(
            token_hash=hash_refresh_token(raw_refresh),
            staff_user_id=staff_user_id,
            client_user_id=client_user_id,
            client_staff_user_id=client_staff_user_id,
            expires_at=expires_at,
        )
    )
    await db.flush()

    return IssuedTokens(
        access_token=access_token,
        raw_refresh_token=raw_refresh,
        refresh_expires_at_seconds=settings.refresh_token_expire_days * 24 * 3600,
    )


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> tuple[RefreshToken, IssuedTokens] | None:
    """Validates and rotates a refresh token. Returns None if the token is
    invalid, expired, or already revoked. Reuse of a revoked token
    (possible theft) revokes the whole chain defensively.
    """
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    existing = result.scalar_one_or_none()

    if existing is None:
        return None

    if existing.revoked_at is not None:
        # Reuse of an already-rotated/revoked token — treat as compromise
        # and revoke every other live token for this subject.
        await _revoke_all_for_subject(db, existing)
        return None

    if existing.expires_at < utcnow():
        return None

    if existing.staff_user_id:
        audience: TokenAudience = "staff"
    elif existing.client_user_id:
        audience = "client"
    else:
        audience = "client_staff"
    new_tokens = await issue_tokens(
        db,
        audience=audience,
        staff_user_id=existing.staff_user_id,
        client_user_id=existing.client_user_id,
        client_staff_user_id=existing.client_staff_user_id,
    )

    existing.revoked_at = utcnow()
    new_hash = hash_refresh_token(new_tokens.raw_refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == new_hash))
    new_row = result.scalar_one()
    existing.replaced_by_id = new_row.id
    await db.flush()

    return existing, new_tokens


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.revoked_at is None:
        existing.revoked_at = utcnow()
        await db.flush()


async def _revoke_all_for_subject(db: AsyncSession, token: RefreshToken) -> None:
    if token.staff_user_id:
        column, value = RefreshToken.staff_user_id, token.staff_user_id
    elif token.client_user_id:
        column, value = RefreshToken.client_user_id, token.client_user_id
    else:
        column, value = RefreshToken.client_staff_user_id, token.client_staff_user_id
    result = await db.execute(select(RefreshToken).where(column == value, RefreshToken.revoked_at.is_(None)))
    for row in result.scalars().all():
        row.revoked_at = utcnow()
    await db.flush()
