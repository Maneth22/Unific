"""Proves `require_identity_scope` blocks a client from reaching an
identity outside their own subtree — the same "try to reach another
group's data with a valid login" test the Flags & Issues doc calls for,
now for the client (Task 2) boundary rather than the staff (Task 1) one.
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.models.client import ClientUser
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password
from app.database import AsyncSessionLocal
from app.profiles import services
from app.profiles.models import Identity, IdentityType
from app.profiles.security import require_identity_scope

_probe_app = FastAPI()
_scope_dep = require_identity_scope()


@_probe_app.get("/probe/{identity_id}")
async def probe(client: ClientUser = Depends(_scope_dep)):
    return {"ok": True}


async def _build_tree_and_client():
    async with AsyncSessionLocal() as db:
        root = await services.create_identity(db, name="Root Co-op", id_type=IdentityType.group, parent_id=None, staff_id=None)
        child = await services.create_identity(db, name="Sub Group", id_type=IdentityType.group, parent_id=root.id, staff_id=None)
        sibling = await services.create_identity(db, name="Sibling Group", id_type=IdentityType.group, parent_id=None, staff_id=None)

        client = ClientUser(
            email="scope-test-client@example.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Scope Test Client",
            identity_id=child.id,
        )
        db.add(client)
        await db.flush()
        client_id = client.id
        await db.commit()
        return root.id, child.id, sibling.id, client_id


async def _cleanup(*identity_and_client_ids):
    root_id, child_id, sibling_id, client_id = identity_and_client_ids
    async with AsyncSessionLocal() as db:
        c = await db.get(ClientUser, client_id)
        if c:
            await db.delete(c)
        await db.commit()

    # Deleting an Identity cascades its Permission/ProfileAccount rows
    # (declared cascade="all, delete-orphan"), but parent_id is
    # ondelete="RESTRICT" — a deliberate safety default, not something
    # to relax. So leaves must be deleted in their own transaction
    # before their parent, one at a time, to avoid batching ambiguity.
    for iid in (child_id, sibling_id, root_id):
        async with AsyncSessionLocal() as db:
            identity = await db.get(Identity, iid)
            if identity:
                await db.delete(identity)
                await db.commit()


@pytest.mark.asyncio
async def test_client_can_reach_own_scope_but_not_ancestor_or_sibling():
    root_id, child_id, sibling_id, client_id = await _build_tree_and_client()
    try:
        token = create_access_token(subject=client_id, audience="client")
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=_probe_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Own identity (self) — allowed.
            resp = await ac.get(f"/probe/{child_id}", headers=headers)
            assert resp.status_code == 200

            # Ancestor — must be blocked even though it's a valid login.
            resp = await ac.get(f"/probe/{root_id}", headers=headers)
            assert resp.status_code == 403

            # An unrelated sibling tree — must also be blocked.
            resp = await ac.get(f"/probe/{sibling_id}", headers=headers)
            assert resp.status_code == 403
    finally:
        await _cleanup(root_id, child_id, sibling_id, client_id)
