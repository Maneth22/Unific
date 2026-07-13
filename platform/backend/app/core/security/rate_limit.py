"""Per-account login lockout, backed by `core.login_attempt`. Deliberately
account-keyed (by email) rather than only IP-keyed, so a distributed
brute-force attempt against one account is still caught.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.common import utcnow
from app.core.models.staff import LoginAttempt


async def is_locked_out(db: AsyncSession, identifier: str) -> bool:
    window_start = utcnow() - timedelta(minutes=settings.login_lockout_minutes)
    result = await db.execute(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.identifier == identifier.lower(),
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= window_start,
        )
    )
    failed_count = result.scalar_one()
    return failed_count >= settings.login_max_attempts


async def record_login_attempt(
    db: AsyncSession, identifier: str, success: bool, ip_address: str | None
) -> None:
    db.add(LoginAttempt(identifier=identifier.lower(), success=success, ip_address=ip_address))
    if success:
        # A successful login clears the failure window for this account.
        window_start = utcnow() - timedelta(minutes=settings.login_lockout_minutes)
        await db.execute(
            LoginAttempt.__table__.delete().where(
                LoginAttempt.identifier == identifier.lower(),
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= window_start,
            )
        )
