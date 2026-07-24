"""Proves the ILC member-registration roster actually enforces what it
claims to: an unrecognized number is rejected, a duplicate claim on an
already-used number is rejected, and a valid unclaimed number succeeds
and marks itself claimed — the same "test the boundary with real data"
shape as test_room_access.py / test_identity_scope.py.
"""
from __future__ import annotations

import pytest

from app.core.models.audit import ActorType
from app.database import AsyncSessionLocal
from app.profiles import services
from app.profiles.models import Identity, IdentityType


async def _build_org_and_ilc_group():
    async with AsyncSessionLocal() as db:
        org = await services.create_client_org_identity(
            db, name="Roster Test Org", actor_type=ActorType.system, actor_id=None
        )
        ilc = await services.create_ilc_group_identity(
            db, name="Roster Test ILC", parent_id=org.id, actor_type=ActorType.system, actor_id=None
        )
        await db.commit()
        return org.id, ilc.id


async def _cleanup(org_id: str, ilc_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(Identity).where(Identity.parent_id == ilc_id)
        )
        for member in result.scalars().all():
            await db.delete(member)
        await db.commit()
    async with AsyncSessionLocal() as db:
        ilc = await db.get(Identity, ilc_id)
        if ilc:
            await db.delete(ilc)
            await db.commit()
    async with AsyncSessionLocal() as db:
        org = await db.get(Identity, org_id)
        if org:
            await db.delete(org)
            await db.commit()


@pytest.mark.asyncio
async def test_roster_valid_duplicate_and_unknown_numbers():
    org_id, ilc_id = await _build_org_and_ilc_group()
    try:
        async with AsyncSessionLocal() as db:
            entries = await services.add_roster_numbers(
                db, group_identity_id=ilc_id, numbers=["001", "002", "001"], actor_client_id=None
            )
            await db.commit()
            # The duplicate "001" in the input list is deduped, not an error.
            assert {e.ilc_registration_number for e in entries} == {"001", "002"}

        # Valid, unclaimed number succeeds.
        async with AsyncSessionLocal() as db:
            member = await services.create_identity(
                db, name="Member A", id_type=IdentityType.member, parent_id=ilc_id,
                actor_type=ActorType.system, actor_id=None,
            )
            profile = await services.create_member_profile(
                db, identity_id=member.id, group_identity_id=ilc_id, ilc_registration_number="001",
                email="", phone_number="+910000000001", extra_info={}, source_invite_id=None,
            )
            await db.commit()
            assert profile.ilc_roster_entry_id is not None

        # Already-claimed number is rejected as a duplicate.
        async with AsyncSessionLocal() as db:
            member_b = await services.create_identity(
                db, name="Member B", id_type=IdentityType.member, parent_id=ilc_id,
                actor_type=ActorType.system, actor_id=None,
            )
            with pytest.raises(services.ProfilesError, match="already been used"):
                await services.create_member_profile(
                    db, identity_id=member_b.id, group_identity_id=ilc_id, ilc_registration_number="001",
                    email="", phone_number="+910000000002", extra_info={}, source_invite_id=None,
                )

        # A number never added to the roster is rejected outright.
        async with AsyncSessionLocal() as db:
            member_c = await services.create_identity(
                db, name="Member C", id_type=IdentityType.member, parent_id=ilc_id,
                actor_type=ActorType.system, actor_id=None,
            )
            with pytest.raises(services.ProfilesError, match="not recognized"):
                await services.create_member_profile(
                    db, identity_id=member_c.id, group_identity_id=ilc_id, ilc_registration_number="does-not-exist",
                    email="", phone_number="+910000000003", extra_info={}, source_invite_id=None,
                )
    finally:
        await _cleanup(org_id, ilc_id)
