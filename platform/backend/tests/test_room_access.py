"""Proves `require_room_access` actually blocks server-side — the
specific test the Flags & Issues doc calls for: "test it by trying to
reach another group's data / room with a valid login."
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.models.common import RoomName, RoomPermission
from app.core.models.staff import StaffRoomAccess, StaffUser
from app.core.security.dependencies import require_room_access
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password
from app.database import AsyncSessionLocal

_probe_app = FastAPI()


@_probe_app.get("/protected/accounts")
async def protected_accounts(
    _staff: StaffUser = Depends(require_room_access(RoomName.accounts, RoomPermission.write)),
):
    return {"ok": True}


@pytest.mark.asyncio
async def test_room_access_denied_without_grant():
    async with AsyncSessionLocal() as db:
        no_access = StaffUser(
            email="no-access-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="No Access Test",
        )
        db.add(no_access)
        await db.flush()
        no_access_id = no_access.id
        await db.commit()

    try:
        token = create_access_token(subject=no_access_id, audience="staff")
        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/protected/accounts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            existing = await db.get(StaffUser, no_access_id)
            if existing:
                await db.delete(existing)
                await db.commit()


@pytest.mark.asyncio
async def test_room_access_allowed_with_sufficient_grant():
    async with AsyncSessionLocal() as db:
        staff = StaffUser(
            email="with-access-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="With Access Test",
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
        db.add(StaffRoomAccess(staff_user_id=staff_id, room=RoomName.accounts, permission=RoomPermission.write))
        await db.commit()

    try:
        token = create_access_token(subject=staff_id, audience="staff")
        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/protected/accounts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        async with AsyncSessionLocal() as db:
            existing = await db.get(StaffUser, staff_id)
            if existing:
                await db.delete(existing)
                await db.commit()


@pytest.mark.asyncio
async def test_room_access_denied_with_insufficient_permission_level():
    """Read-only access must not satisfy a write-level requirement."""
    async with AsyncSessionLocal() as db:
        staff = StaffUser(
            email="read-only-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Read Only Test",
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
        db.add(StaffRoomAccess(staff_user_id=staff_id, room=RoomName.accounts, permission=RoomPermission.read))
        await db.commit()

    try:
        token = create_access_token(subject=staff_id, audience="staff")
        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/protected/accounts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            existing = await db.get(StaffUser, staff_id)
            if existing:
                await db.delete(existing)
                await db.commit()
