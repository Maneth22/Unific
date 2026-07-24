"""Auth dependencies for staff (master dashboard) routes. Client-scoped
dependencies (`require_identity_scope`) live in `app.profiles.security`.

Two tiers: `StaffTier.admin` gets every existing admin route (clients,
cost/API data, staff management, meeting scheduling); `StaffTier.staff` is
deliberately narrow — their own tasks/updates/inbox only (`app.tasking`).
`require_admin` gates the former, `require_any_staff` the latter/shared
routes (e.g. `GET /auth/me`, joining a meeting one was invited to). This
reverses the previous "every staff account is a full Admin" collapse by
deliberate choice — see `app.core.models.staff.StaffUser`'s docstring.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.staff import StaffTier, StaffUser
from app.core.security.jwt import decode_access_token
from app.database import get_db

_bearer = HTTPBearer(auto_error=False)


async def get_current_staff_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> StaffUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials, audience="staff")
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    staff_id = payload.get("sub")
    result = await db.execute(select(StaffUser).where(StaffUser.id == staff_id))
    staff_user = result.scalar_one_or_none()
    if staff_user is None or not staff_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
    return staff_user


async def require_any_staff(current_staff: StaffUser = Depends(get_current_staff_user)) -> StaffUser:
    """Any active staff account, admin or not — for routes both tiers use
    (a staff member's own profile, their own tasks/inbox, joining a
    meeting they were invited to)."""
    return current_staff


async def require_admin(current_staff: StaffUser = Depends(get_current_staff_user)) -> StaffUser:
    """Only `StaffTier.admin` passes. Every accounts/profiles/meeting-
    scheduling route in this app stays gated by this — regular staff never
    see client data, cost/API dashboards, or another staff member's tasks."""
    if current_staff.tier != StaffTier.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_staff


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
