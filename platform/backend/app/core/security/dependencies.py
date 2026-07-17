"""Auth dependencies for staff (master dashboard) routes. Client-scoped
dependencies (`require_identity_scope`) live in `app.profiles.security`.

There is no per-room grant model — every active staff account is a full
Admin. `require_admin` is the single server-side gate every accounts/
profiles/meeting-room staff route depends on (the UI showing/hiding a nav
item is not access control, this dependency is); it used to be
`require_room_access(room, minimum)` checking a `StaffRoomAccess` row, but
that per-room grant table was removed when staff roles were collapsed to
one Admin role.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.staff import StaffUser
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


async def require_admin(current_staff: StaffUser = Depends(get_current_staff_user)) -> StaffUser:
    """Named wrapper around `get_current_staff_user` so router code reads
    self-documenting (`Depends(require_admin)`) rather than depending on
    the generic accessor directly. Any active staff account passes."""
    return current_staff


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
