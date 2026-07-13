"""Auth dependencies for staff (master dashboard) routes. Client-scoped
dependencies (`require_identity_scope`) are added in `app.profiles.security`
once the identity tree exists (Phase C) — they follow the same shape.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName, RoomPermission
from app.core.models.staff import StaffRoomAccess, StaffUser
from app.core.security.jwt import decode_access_token
from app.database import get_db

_bearer = HTTPBearer(auto_error=False)

_PERMISSION_RANK = {RoomPermission.read: 0, RoomPermission.write: 1, RoomPermission.admin: 2}


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


def require_room_access(room: RoomName, minimum: RoomPermission = RoomPermission.read):
    """Enforces the master-dashboard grant model server-side: a staff user
    must hold an explicit `StaffRoomAccess` row for `room` at or above
    `minimum`, unless they are superadmin. This is the check every
    accounts/profiles/meeting-room staff route depends on — the UI hiding
    a nav item is not access control, this dependency is.
    """

    async def checker(
        current_staff: StaffUser = Depends(get_current_staff_user),
        db: AsyncSession = Depends(get_db),
    ) -> StaffUser:
        if current_staff.is_superadmin:
            return current_staff

        result = await db.execute(
            select(StaffRoomAccess).where(
                StaffRoomAccess.staff_user_id == current_staff.id,
                StaffRoomAccess.room == room,
            )
        )
        access = result.scalar_one_or_none()
        if access is None or _PERMISSION_RANK[access.permission] < _PERMISSION_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{minimum.value}' access to room '{room.value}'",
            )
        return current_staff

    return checker


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
