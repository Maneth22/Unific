"""Proves the client-staff (limited) vs client-owner (full) split actually
holds server-side: a `ClientStaffUser` token can reach identity-scoped
community routes (`require_identity_scope()`, the default) but is
rejected from owner-only money routes
(`require_identity_scope(owner_only=True)` / `require_client_owner`) —
enforced by audience-typing (a client-staff token can't even decode as
`audience="client"`), not a role flag. Same "valid login, wrong scope/tier"
shape as test_room_access.py / test_identity_scope.py.
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.models.audit import ActorType
from app.core.models.client import ClientStaffUser, ClientUser
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password
from app.database import AsyncSessionLocal
from app.profiles import services
from app.profiles.security import require_client_owner, require_identity_scope

_probe_app = FastAPI()
_scope_any = require_identity_scope()
_scope_owner = require_identity_scope(owner_only=True)


@_probe_app.get("/probe/community/{identity_id}")
async def probe_community(client=Depends(_scope_any)):
    return {"ok": True}


@_probe_app.get("/probe/money/{identity_id}")
async def probe_money(client=Depends(_scope_owner)):
    return {"ok": True}


@_probe_app.get("/probe/owner-only")
async def probe_owner_only(client: ClientUser = Depends(require_client_owner)):
    return {"ok": True}


async def _build_org_owner_and_staff():
    async with AsyncSessionLocal() as db:
        org = await services.create_client_org_identity(db, name="Client Staff Scope Org", actor_type=ActorType.system, actor_id=None)
        owner = ClientUser(
            email="scope-owner@example.org", password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Owner", identity_id=org.id,
        )
        db.add(owner)
        await db.flush()
        client_staff = ClientStaffUser(
            email="scope-staff@example.org", password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Staff", identity_id=org.id, created_by_client_id=owner.id,
        )
        db.add(client_staff)
        await db.flush()
        org_id, owner_id, staff_id = org.id, owner.id, client_staff.id
        await db.commit()
        return org_id, owner_id, staff_id


async def _cleanup(org_id: str, owner_id: str, staff_id: str):
    async with AsyncSessionLocal() as db:
        s = await db.get(ClientStaffUser, staff_id)
        if s:
            await db.delete(s)
        o = await db.get(ClientUser, owner_id)
        if o:
            await db.delete(o)
        await db.commit()
    async with AsyncSessionLocal() as db:
        from app.profiles.models import Identity

        i = await db.get(Identity, org_id)
        if i:
            await db.delete(i)
            await db.commit()


@pytest.mark.asyncio
async def test_client_staff_reaches_community_but_not_money_or_owner_only():
    org_id, owner_id, staff_id = await _build_org_owner_and_staff()
    try:
        staff_token = create_access_token(subject=staff_id, audience="client_staff")
        owner_token = create_access_token(subject=owner_id, audience="client")
        staff_headers = {"Authorization": f"Bearer {staff_token}"}
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Client staff: community/ILC routes (general scope) — allowed.
            resp = await ac.get(f"/probe/community/{org_id}", headers=staff_headers)
            assert resp.status_code == 200

            # Client staff: money routes (owner_only scope) — rejected.
            resp = await ac.get(f"/probe/money/{org_id}", headers=staff_headers)
            assert resp.status_code == 401

            # Client staff: owner-only management routes — rejected outright,
            # since a client_staff token can't decode as audience="client".
            resp = await ac.get("/probe/owner-only", headers=staff_headers)
            assert resp.status_code == 401

            # The org owner, for contrast, passes all three.
            resp = await ac.get(f"/probe/community/{org_id}", headers=owner_headers)
            assert resp.status_code == 200
            resp = await ac.get(f"/probe/money/{org_id}", headers=owner_headers)
            assert resp.status_code == 200
            resp = await ac.get("/probe/owner-only", headers=owner_headers)
            assert resp.status_code == 200
    finally:
        await _cleanup(org_id, owner_id, staff_id)
