"""Proves `require_admin`/`require_any_staff` actually enforce something
server-side — the specific test the Flags & Issues doc calls for: "test it
by trying to reach another group's data / room with a valid login." Two
tiers now (see `app.core.security.dependencies`): `require_admin` only
passes `StaffTier.admin`; `require_any_staff` passes either tier. An
inactive account and an unauthenticated request are both rejected
regardless of tier.
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.models.staff import StaffTier, StaffUser
from app.core.security.dependencies import require_admin, require_any_staff
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password
from app.database import AsyncSessionLocal

_probe_app = FastAPI()


@_probe_app.get("/protected/accounts")
async def protected_accounts(_staff: StaffUser = Depends(require_admin)):
    return {"ok": True}


@_probe_app.get("/shared/any-staff")
async def shared_any_staff(_staff: StaffUser = Depends(require_any_staff)):
    return {"ok": True}


@pytest.mark.asyncio
async def test_admin_denied_without_token():
    transport = ASGITransport(app=_probe_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/protected/accounts")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_allowed_for_admin_tier_staff():
    async with AsyncSessionLocal() as db:
        staff = StaffUser(
            email="admin-access-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Admin Access Test",
            tier=StaffTier.admin,
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
async def test_admin_denied_for_staff_tier_but_any_staff_allowed():
    async with AsyncSessionLocal() as db:
        staff = StaffUser(
            email="staff-tier-access-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Staff Tier Access Test",
            tier=StaffTier.staff,
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
        await db.commit()

    try:
        token = create_access_token(subject=staff_id, audience="staff")
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # A logged-in, active, but non-admin staff account must be
            # rejected from an admin-only route...
            resp = await ac.get("/protected/accounts", headers=headers)
            assert resp.status_code == 403
            # ...but allowed into a route both tiers share.
            resp = await ac.get("/shared/any-staff", headers=headers)
            assert resp.status_code == 200
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
