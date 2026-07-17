"""Proves `require_admin` actually enforces something server-side — the
specific test the Flags & Issues doc calls for: "test it by trying to
reach another group's data / room with a valid login." There is no
per-room grant model any more (see `app.core.security.dependencies`), so
this now proves the collapsed boundary: any active staff account passes,
an inactive one is rejected, and an unauthenticated request is rejected.
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.models.staff import StaffUser
from app.core.security.dependencies import require_admin
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password
from app.database import AsyncSessionLocal

_probe_app = FastAPI()


@_probe_app.get("/protected/accounts")
async def protected_accounts(_staff: StaffUser = Depends(require_admin)):
    return {"ok": True}


@pytest.mark.asyncio
async def test_admin_denied_without_token():
    transport = ASGITransport(app=_probe_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/protected/accounts")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_allowed_for_any_active_staff():
    async with AsyncSessionLocal() as db:
        staff = StaffUser(
            email="admin-access-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Admin Access Test",
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
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
async def test_admin_denied_for_inactive_staff():
    async with AsyncSessionLocal() as db:
        staff = StaffUser(
            email="inactive-admin-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Inactive Admin Test",
            is_active=False,
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
        await db.commit()

    try:
        token = create_access_token(subject=staff_id, audience="staff")
        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/protected/accounts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
    finally:
        async with AsyncSessionLocal() as db:
            existing = await db.get(StaffUser, staff_id)
            if existing:
                await db.delete(existing)
                await db.commit()
