"""Proves the LiveKit meeting flow's server-side guarantees against the
mock video provider: scheduling creates participants + invites, a join
transitions scheduled -> live, a client/public join is rejected when the
caller isn't actually a participant on that meeting or holds an
expired/revoked invite — the same "test it with a valid login that
shouldn't reach this" shape as test_room_access.py / test_identity_scope.py.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.models.audit import ActorType
from app.core.models.client import ClientUser
from app.core.models.common import utcnow
from app.core.models.staff import StaffUser
from app.core.providers.mock_video_provider import MockVideoProvider
from app.core.security.password import hash_password
from app.database import AsyncSessionLocal
from app.meeting_room import services
from app.meeting_room.models import Meeting, MeetingInvite, MeetingParticipant, MeetingStatus
from app.profiles import services as profiles_services
from app.profiles.models import Identity, IdentityType


async def _build_tree_and_staff():
    async with AsyncSessionLocal() as db:
        host = await profiles_services.create_identity(
            db, name="Meeting Host Co-op", id_type=IdentityType.group, parent_id=None,
            actor_type=ActorType.system, actor_id=None,
        )
        outsider = await profiles_services.create_identity(
            db, name="Unrelated Group", id_type=IdentityType.group, parent_id=None,
            actor_type=ActorType.system, actor_id=None,
        )
        staff = StaffUser(
            email="meeting-video-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Meeting Video Test Staff",
        )
        db.add(staff)
        await db.flush()
        staff_id = staff.id
        await db.commit()
        return host.id, outsider.id, staff_id


async def _cleanup(host_id: str, outsider_id: str, staff_id: str, meeting_id: str | None):
    async with AsyncSessionLocal() as db:
        if meeting_id:
            meeting = await db.get(Meeting, meeting_id)
            if meeting:
                await db.delete(meeting)  # cascades participants + invites
        staff = await db.get(StaffUser, staff_id)
        if staff:
            await db.delete(staff)
        await db.commit()

    for iid in (host_id, outsider_id):
        async with AsyncSessionLocal() as db:
            identity = await db.get(Identity, iid)
            if identity:
                await db.delete(identity)
                await db.commit()


@pytest.mark.asyncio
async def test_schedule_meeting_creates_participants_and_invites():
    host_id, outsider_id, staff_id = await _build_tree_and_staff()
    meeting_id = None
    try:
        async with AsyncSessionLocal() as db:
            meeting = await services.schedule_meeting(
                db,
                host_identity_id=host_id,
                scheduled_at=utcnow() + timedelta(hours=1),
                translate_live=False,
                staff_id=staff_id,
                video_provider=MockVideoProvider(),
            )
            meeting_id = meeting.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            meeting = await services.get_meeting_with_participants(db, meeting_id)
            assert meeting.room_name == f"meeting-{meeting_id}"
            assert meeting.status == MeetingStatus.scheduled
            assert len(meeting.participants) == 2  # host identity + scheduling staff
            identity_participants = [p for p in meeting.participants if p.identity_id == host_id]
            assert len(identity_participants) == 1

            invites = await services.get_invites_for_meeting(db, meeting_id)
            assert len(invites) == 1  # one per identity-side participant, none for staff
            assert invites[0].participant_id == identity_participants[0].id
    finally:
        await _cleanup(host_id, outsider_id, staff_id, meeting_id)


@pytest.mark.asyncio
async def test_staff_join_transitions_meeting_to_live():
    host_id, outsider_id, staff_id = await _build_tree_and_staff()
    meeting_id = None
    try:
        async with AsyncSessionLocal() as db:
            meeting = await services.schedule_meeting(
                db,
                host_identity_id=host_id,
                scheduled_at=utcnow() + timedelta(hours=1),
                translate_live=False,
                staff_id=staff_id,
                video_provider=MockVideoProvider(),
            )
            meeting_id = meeting.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            meeting, token = await services.mint_staff_join(
                db, meeting_id=meeting_id, staff_id=staff_id, staff_name="Meeting Video Test Staff",
                video_provider=MockVideoProvider(),
            )
            await db.commit()
            assert meeting.status == MeetingStatus.live
            assert meeting.started_at is not None
            assert token == f"mock-token:{meeting.room_name}:staff:{staff_id}"
    finally:
        await _cleanup(host_id, outsider_id, staff_id, meeting_id)


@pytest.mark.asyncio
async def test_client_join_rejected_when_not_a_participant():
    host_id, outsider_id, staff_id = await _build_tree_and_staff()
    meeting_id = None
    try:
        async with AsyncSessionLocal() as db:
            meeting = await services.schedule_meeting(
                db,
                host_identity_id=host_id,
                scheduled_at=utcnow() + timedelta(hours=1),
                translate_live=False,
                staff_id=staff_id,
                video_provider=MockVideoProvider(),
            )
            meeting_id = meeting.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            with pytest.raises(services.MeetingRoomError):
                await services.mint_client_join(
                    db, meeting_id=meeting_id, identity_id=outsider_id, video_provider=MockVideoProvider()
                )
    finally:
        await _cleanup(host_id, outsider_id, staff_id, meeting_id)


class _SpyVideoProvider(MockVideoProvider):
    """Records end_room calls so the delete test can prove the LiveKit
    room was actually asked to close, not just the DB row removed."""

    def __init__(self):
        self.ended_rooms: list[str] = []

    async def end_room(self, room_name: str) -> None:
        self.ended_rooms.append(room_name)
        await super().end_room(room_name)


@pytest.mark.asyncio
async def test_delete_meeting_ends_livekit_room_and_removes_it():
    host_id, outsider_id, staff_id = await _build_tree_and_staff()
    meeting_id = None
    try:
        async with AsyncSessionLocal() as db:
            meeting = await services.schedule_meeting(
                db,
                host_identity_id=host_id,
                scheduled_at=utcnow() + timedelta(hours=1),
                translate_live=False,
                staff_id=staff_id,
                video_provider=MockVideoProvider(),
            )
            meeting_id = meeting.id
            room_name = meeting.room_name
            await db.commit()

        spy = _SpyVideoProvider()
        async with AsyncSessionLocal() as db:
            await services.delete_meeting(db, meeting_id=meeting_id, staff_id=staff_id, video_provider=spy)
            await db.commit()

        assert spy.ended_rooms == [room_name]

        async with AsyncSessionLocal() as db:
            assert await db.get(Meeting, meeting_id) is None
            remaining = await db.execute(
                select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
            )
            assert remaining.first() is None
        meeting_id = None  # already deleted — nothing left for _cleanup to remove
    finally:
        await _cleanup(host_id, outsider_id, staff_id, meeting_id)


@pytest.mark.asyncio
async def test_public_join_rejected_for_expired_or_revoked_invite():
    host_id, outsider_id, staff_id = await _build_tree_and_staff()
    meeting_id = None
    try:
        async with AsyncSessionLocal() as db:
            meeting = await services.schedule_meeting(
                db,
                host_identity_id=host_id,
                scheduled_at=utcnow() + timedelta(hours=1),
                translate_live=False,
                staff_id=staff_id,
                video_provider=MockVideoProvider(),
            )
            meeting_id = meeting.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            invites = await services.get_invites_for_meeting(db, meeting_id)
            expired_invite, revoked_invite = invites[0], invites[0]
            expired_invite.expires_at = utcnow() - timedelta(hours=1)
            await db.commit()

        async with AsyncSessionLocal() as db:
            with pytest.raises(services.MeetingRoomError):
                await services.mint_public_join(db, token=expired_invite.token, video_provider=MockVideoProvider())

        async with AsyncSessionLocal() as db:
            invite = await db.get(MeetingInvite, expired_invite.id)
            invite.expires_at = utcnow() + timedelta(hours=1)
            invite.revoked_at = utcnow()
            await db.commit()

        async with AsyncSessionLocal() as db:
            with pytest.raises(services.MeetingRoomError):
                await services.mint_public_join(db, token=revoked_invite.token, video_provider=MockVideoProvider())
    finally:
        await _cleanup(host_id, outsider_id, staff_id, meeting_id)


@pytest.mark.asyncio
async def test_client_org_meeting_kind_rejects_ilc_community_identity():
    """The admin "meet with a client" picker (meeting_kind="client_org")
    must never accept an ILC/community identity — only client-org roots."""
    async with AsyncSessionLocal() as db:
        org = await profiles_services.create_client_org_identity(
            db, name="Meeting Kind Test Org", actor_type=ActorType.system, actor_id=None
        )
        ilc = await profiles_services.create_ilc_group_identity(
            db, name="Meeting Kind Test ILC", parent_id=org.id, actor_type=ActorType.system, actor_id=None
        )
        staff = StaffUser(
            email="meeting-kind-test@landchange.org",
            password_hash=hash_password("irrelevant-not-used-12345"),
            full_name="Meeting Kind Test Staff",
        )
        db.add(staff)
        await db.flush()
        org_id, ilc_id, staff_id = org.id, ilc.id, staff.id
        await db.commit()

    meeting_id = None
    try:
        # The org root itself is a valid client_org meeting participant.
        async with AsyncSessionLocal() as db:
            meeting = await services.schedule_meeting(
                db, host_identity_id=org_id, scheduled_at=utcnow() + timedelta(hours=1), translate_live=False,
                staff_id=staff_id, meeting_kind="client_org", video_provider=MockVideoProvider(),
            )
            meeting_id = meeting.id
            await db.commit()

        # The ILC community identity must be rejected as a client_org participant.
        async with AsyncSessionLocal() as db:
            with pytest.raises(services.MeetingRoomError, match="never an ILC/community identity"):
                await services.schedule_meeting(
                    db, host_identity_id=ilc_id, scheduled_at=utcnow() + timedelta(hours=1), translate_live=False,
                    staff_id=staff_id, meeting_kind="client_org", video_provider=MockVideoProvider(),
                )
    finally:
        async with AsyncSessionLocal() as db:
            if meeting_id:
                m = await db.get(Meeting, meeting_id)
                if m:
                    await db.delete(m)
            s = await db.get(StaffUser, staff_id)
            if s:
                await db.delete(s)
            await db.commit()
        async with AsyncSessionLocal() as db:
            i = await db.get(Identity, ilc_id)
            if i:
                await db.delete(i)
                await db.commit()
        async with AsyncSessionLocal() as db:
            i = await db.get(Identity, org_id)
            if i:
                await db.delete(i)
                await db.commit()
