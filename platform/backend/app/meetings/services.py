"""New meetings schema business logic — mirrors
`app.meeting_room.services`'s meeting-lifecycle functions closely,
retargeted at `orgs.Org`/`orgs.Member`/`orgs.OrgUser` instead of
`profiles.Identity`. `app.meeting_room.services` itself is untouched.

`_mark_joined` is this phase's crux: the entitlement check
(`entitlement_service.has`) happens exactly once, at the scheduled->live
transition, exactly mirroring the old `_mark_joined`'s "resolve the
Tools Registry choice exactly once" timing discipline — never re-checked
for an already-live meeting.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow, uuid_str
from app.core.providers.base import ProviderError, VideoProvider
from app.core.services import audit_service, tools_service
from app.core.services.tools_service import EffectiveToolConfig
from app.meeting_room import live_agents
from app.meetings import session_store
from app.meetings.models import MeetingInviteKind, MeetingStatus, OrgMeeting, OrgMeetingInvite, OrgMeetingParticipant
from app.plugins import services as entitlement_service

logger = logging.getLogger(__name__)

_JOINABLE_STATUSES = (MeetingStatus.scheduled, MeetingStatus.live)
LIVE_TRANSLATION_PLUGIN_KEY = "live_translation"


class MeetingsError(Exception):
    pass


def build_invite_url(token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/meetings/join/{token}"


async def _create_personal_invite(
    db: AsyncSession, *, meeting_id: str, member_id: str, expires_at: datetime
) -> tuple[OrgMeetingParticipant, OrgMeetingInvite]:
    participant = OrgMeetingParticipant(meeting_id=meeting_id, member_id=member_id)
    db.add(participant)
    await db.flush()
    invite = OrgMeetingInvite(meeting_id=meeting_id, participant_id=participant.id, kind=MeetingInviteKind.personal, expires_at=expires_at)
    db.add(invite)
    await db.flush()
    return participant, invite


async def _create_open_invite(db: AsyncSession, *, meeting_id: str, expires_at: datetime) -> OrgMeetingInvite:
    invite = OrgMeetingInvite(meeting_id=meeting_id, participant_id=None, kind=MeetingInviteKind.open, expires_at=expires_at)
    db.add(invite)
    await db.flush()
    return invite


async def schedule_meeting(
    db: AsyncSession,
    *,
    org_id: str | None,
    scheduled_at: datetime,
    translate_live: bool,
    translate_languages: list[str],
    org_user_id: str | None = None,
    staff_id: str | None = None,
    notes: str = "",
    participant_member_ids: list[str] | None = None,
    participant_org_user_ids: list[str] | None = None,
    video_provider: VideoProvider,
) -> OrgMeeting:
    """Mirrors `app.meeting_room.services.schedule_meeting`: creates the
    room (aborts scheduling on failure — a meeting with no room is
    useless), the Meeting row, one participant+invite per member, one
    participant per org_user, one open invite. Does NOT check any
    entitlement here — `translate_live`/`translate_languages` are just
    stored, unchecked, exactly like the old function; the check happens
    once at the scheduled->live transition (`_mark_joined`)."""
    actor_type = ActorType.staff if staff_id else ActorType.org_user
    actor_id = staff_id or org_user_id

    if scheduled_at.tzinfo is not None:
        scheduled_at = scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)

    meeting_id = uuid_str()
    room_name = f"meeting-{meeting_id}"
    try:
        await video_provider.create_room(room_name)
    except ProviderError as exc:
        raise MeetingsError(f"Could not create the video conferencing room: {exc}") from exc

    meeting = OrgMeeting(
        id=meeting_id, org_id=org_id, scheduled_at=scheduled_at, translate_live=translate_live,
        translate_languages=translate_languages, notes=notes,
        created_by_staff_id=staff_id, created_by_org_user_id=org_user_id, room_name=room_name,
    )
    db.add(meeting)
    await db.flush()

    for sid in {staff_id} - {None}:
        db.add(OrgMeetingParticipant(meeting_id=meeting.id, staff_user_id=sid))
    for ouid in {org_user_id, *(participant_org_user_ids or [])} - {None}:
        db.add(OrgMeetingParticipant(meeting_id=meeting.id, org_user_id=ouid))

    invite_expires_at = scheduled_at + timedelta(hours=settings.meeting_invite_ttl_hours)
    for member_id in set(participant_member_ids or []):
        await _create_personal_invite(db, meeting_id=meeting.id, member_id=member_id, expires_at=invite_expires_at)

    await _create_open_invite(db, meeting_id=meeting.id, expires_at=invite_expires_at)

    await audit_service.record(
        db, actor_type=actor_type, actor_id=actor_id, action="meetings.meeting.schedule",
        room=RoomName.meetings, entity_type="meeting", entity_id=meeting.id,
    )
    return meeting


async def add_participant(
    db: AsyncSession, *, meeting_id: str, member_id: str | None = None, org_user_id: str | None = None,
    staff_id: str | None = None, actor_type: ActorType, actor_id: str | None,
) -> tuple[OrgMeetingParticipant, OrgMeetingInvite | None]:
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise MeetingsError("Meeting not found")
    _assert_joinable(meeting)

    if member_id is not None:
        existing = await db.execute(
            select(OrgMeetingParticipant).where(OrgMeetingParticipant.meeting_id == meeting_id, OrgMeetingParticipant.member_id == member_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise MeetingsError("This person is already a participant on this meeting")
        invite_expires_at = meeting.scheduled_at + timedelta(hours=settings.meeting_invite_ttl_hours)
        participant, invite = await _create_personal_invite(db, meeting_id=meeting.id, member_id=member_id, expires_at=invite_expires_at)
    elif org_user_id is not None:
        existing = await db.execute(
            select(OrgMeetingParticipant).where(OrgMeetingParticipant.meeting_id == meeting_id, OrgMeetingParticipant.org_user_id == org_user_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise MeetingsError("This person is already a participant on this meeting")
        participant = OrgMeetingParticipant(meeting_id=meeting_id, org_user_id=org_user_id)
        db.add(participant)
        await db.flush()
        invite = None
    else:
        existing = await db.execute(
            select(OrgMeetingParticipant).where(OrgMeetingParticipant.meeting_id == meeting_id, OrgMeetingParticipant.staff_user_id == staff_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise MeetingsError("This person is already a participant on this meeting")
        participant = OrgMeetingParticipant(meeting_id=meeting_id, staff_user_id=staff_id)
        db.add(participant)
        await db.flush()
        invite = None

    await audit_service.record(
        db, actor_type=actor_type, actor_id=actor_id, action="meetings.meeting.add_participant",
        room=RoomName.meetings, entity_type="meeting", entity_id=meeting.id,
        after={"member_id": member_id, "org_user_id": org_user_id, "staff_user_id": staff_id},
    )
    return participant, invite


async def list_meetings(db: AsyncSession) -> list[OrgMeeting]:
    result = await db.execute(select(OrgMeeting).order_by(OrgMeeting.scheduled_at))
    return list(result.scalars().all())


async def list_org_meetings(db: AsyncSession, org_id: str) -> list[OrgMeeting]:
    result = await db.execute(select(OrgMeeting).where(OrgMeeting.org_id == org_id).order_by(OrgMeeting.scheduled_at.desc()))
    return list(result.scalars().all())


async def get_meeting_with_participants(db: AsyncSession, meeting_id: str) -> OrgMeeting | None:
    from sqlalchemy.orm import selectinload

    result = await db.execute(select(OrgMeeting).options(selectinload(OrgMeeting.participants)).where(OrgMeeting.id == meeting_id))
    return result.scalar_one_or_none()


async def get_open_invite(db: AsyncSession, meeting_id: str) -> OrgMeetingInvite | None:
    result = await db.execute(select(OrgMeetingInvite).where(OrgMeetingInvite.meeting_id == meeting_id, OrgMeetingInvite.kind == MeetingInviteKind.open))
    return result.scalar_one_or_none()


async def get_invite_by_token(db: AsyncSession, token: str) -> OrgMeetingInvite | None:
    result = await db.execute(select(OrgMeetingInvite).where(OrgMeetingInvite.token == token))
    invite = result.scalar_one_or_none()
    if invite is None or not invite.is_active or invite.revoked_at is not None:
        return None
    if invite.expires_at < utcnow():
        return None
    return invite


async def get_public_join_info(db: AsyncSession, token: str):
    invite = await get_invite_by_token(db, token)
    if invite is None:
        return None
    meeting = await db.get(OrgMeeting, invite.meeting_id)
    if meeting is None:
        return None
    if invite.kind == MeetingInviteKind.open:
        return meeting, None, invite.kind
    participant = await db.get(OrgMeetingParticipant, invite.participant_id)
    if participant is None:
        return None
    return meeting, participant, invite.kind


def _assert_joinable(meeting: OrgMeeting) -> None:
    if meeting.status not in _JOINABLE_STATUSES:
        raise MeetingsError(f"This meeting is {meeting.status.value} and can no longer be joined")


async def _mark_joined(
    db: AsyncSession, *, meeting: OrgMeeting, participant: OrgMeetingParticipant, actor_type: ActorType, actor_id: str | None
) -> None:
    now = utcnow()
    participant.joined_at = now
    if meeting.status == MeetingStatus.scheduled:
        meeting.status = MeetingStatus.live
        meeting.started_at = now
        translation_started = False
        if meeting.translate_live and meeting.org_id is not None:
            # THE one place entitlement_service.has is ever called for
            # this meeting — captured once, here, never re-checked for
            # any subsequent join to this same meeting (mirrors the old
            # _mark_joined's tools_service.resolve_effective_tools timing
            # exactly).
            entitled = await entitlement_service.has(db, meeting.org_id, LIVE_TRANSLATION_PLUGIN_KEY)
            if entitled:
                admitted = await session_store.try_acquire_meeting_slot(
                    meeting.id, limit=settings.max_concurrent_livekit_sessions,
                    ttl_seconds=settings.meeting_concurrency_slot_ttl_seconds,
                )
                if admitted:
                    try:
                        tool_config = EffectiveToolConfig(
                            reply_generator="", comms_agent="", meeting_translation="gemini",
                            meeting_stt=dict(settings.live_agents_stt_provider_map_dict),
                            meeting_tts=dict(settings.live_agents_tts_provider_map_dict),
                        )
                        await live_agents.start_for_meeting(
                            room_name=meeting.room_name, meeting_id=meeting.id,
                            languages=meeting.translate_languages, tool_config=tool_config,
                        )
                        translation_started = True
                    except Exception:
                        logger.exception("failed to start live translation meeting_id=%s", meeting.id)
                        await session_store.release_meeting_slot(meeting.id)
                else:
                    logger.warning(
                        "MAX_CONCURRENT_LIVEKIT_SESSIONS reached — meeting %s starts video-only", meeting.id
                    )
        meeting.translation_active = translation_started
    await audit_service.record(
        db, actor_type=actor_type, actor_id=actor_id, action="meetings.meeting.join",
        room=RoomName.meetings, entity_type="meeting", entity_id=meeting.id,
    )
    await db.flush()


async def mint_staff_join(db: AsyncSession, *, meeting_id: str, staff_id: str, staff_name: str, video_provider: VideoProvider) -> tuple[OrgMeeting, str]:
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise MeetingsError("Meeting not found")
    _assert_joinable(meeting)

    result = await db.execute(select(OrgMeetingParticipant).where(OrgMeetingParticipant.meeting_id == meeting_id, OrgMeetingParticipant.staff_user_id == staff_id))
    participant = result.scalar_one_or_none()
    if participant is None:
        participant = OrgMeetingParticipant(meeting_id=meeting_id, staff_user_id=staff_id)
        db.add(participant)
        await db.flush()

    token = await video_provider.generate_access_token(
        room_name=meeting.room_name, participant_identity=f"staff:{staff_id}", participant_name=staff_name,
        ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.staff, actor_id=staff_id)
    return meeting, token


async def mint_org_user_join(db: AsyncSession, *, meeting_id: str, org_user_id: str, org_user_name: str, video_provider: VideoProvider) -> tuple[OrgMeeting, str]:
    """`org_user_id` must already be scope-checked by the caller (router)
    against the caller's own org — this only checks it's actually a
    participant on this specific meeting."""
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise MeetingsError("Meeting not found")
    _assert_joinable(meeting)

    result = await db.execute(select(OrgMeetingParticipant).where(OrgMeetingParticipant.meeting_id == meeting_id, OrgMeetingParticipant.org_user_id == org_user_id))
    participant = result.scalar_one_or_none()
    if participant is None:
        raise MeetingsError("This org user is not a participant on this meeting")

    token = await video_provider.generate_access_token(
        room_name=meeting.room_name, participant_identity=f"org_user:{org_user_id}", participant_name=org_user_name,
        ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.org_user, actor_id=org_user_id)
    return meeting, token


async def mint_public_join(db: AsyncSession, *, token: str, video_provider: VideoProvider) -> tuple[OrgMeeting, str]:
    info = await get_public_join_info(db, token)
    if info is None:
        raise MeetingsError("This meeting link is invalid or has expired")
    meeting, participant, kind = info
    if kind != MeetingInviteKind.personal or participant is None:
        raise MeetingsError("This is not a personal invite link")
    _assert_joinable(meeting)

    token_jwt = await video_provider.generate_access_token(
        room_name=meeting.room_name, participant_identity=f"member:{participant.member_id}",
        participant_name="Guest", ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )

    invite = await get_invite_by_token(db, token)
    if invite is not None:
        invite.used_at = utcnow()
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.system, actor_id=None)
    return meeting, token_jwt


async def redeem_open_invite(db: AsyncSession, *, token: str, guest_name: str, video_provider: VideoProvider) -> tuple[OrgMeeting, str]:
    invite = await get_invite_by_token(db, token)
    if invite is None or invite.kind != MeetingInviteKind.open:
        raise MeetingsError("This meeting link is invalid or has expired")
    meeting = await db.get(OrgMeeting, invite.meeting_id)
    if meeting is None:
        raise MeetingsError("Meeting not found")
    _assert_joinable(meeting)

    guest_name = (guest_name or "").strip()[:100] or "Guest"
    participant = OrgMeetingParticipant(meeting_id=meeting.id, guest_name=guest_name)
    db.add(participant)
    await db.flush()

    guest_identity = f"guest:{uuid_str()}"
    token_jwt = await video_provider.generate_access_token(
        room_name=meeting.room_name, participant_identity=guest_identity, participant_name=guest_name,
        ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.system, actor_id=None)
    return meeting, token_jwt


async def end_meeting(db: AsyncSession, *, meeting_id: str, video_provider: VideoProvider, staff_id: str | None = None, org_user_id: str | None = None) -> OrgMeeting:
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise MeetingsError("Meeting not found")
    if meeting.status == MeetingStatus.cancelled:
        raise MeetingsError("This meeting was cancelled")

    try:
        await video_provider.end_room(meeting.room_name)
    except ProviderError as exc:
        logger.warning("LiveKit room end failed (marking meeting completed regardless): %s", exc)
    try:
        await live_agents.stop_for_meeting(meeting.id)
    except Exception:
        logger.exception("failed to stop live translation meeting_id=%s", meeting.id)
    try:
        await session_store.release_meeting_slot(meeting.id)
    except Exception:
        logger.exception("failed to release concurrency slot meeting_id=%s", meeting.id)

    meeting.status = MeetingStatus.completed
    meeting.ended_at = utcnow()
    await audit_service.record(
        db, actor_type=ActorType.staff if staff_id else ActorType.org_user, actor_id=staff_id or org_user_id,
        action="meetings.meeting.end", room=RoomName.meetings, entity_type="meeting", entity_id=meeting.id,
    )
    await db.flush()
    return meeting


async def delete_meeting(db: AsyncSession, *, meeting_id: str, staff_id: str, video_provider: VideoProvider) -> None:
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise MeetingsError("Meeting not found")

    try:
        await video_provider.end_room(meeting.room_name)
    except ProviderError as exc:
        logger.warning("LiveKit room end failed (deleting meeting regardless): %s", exc)
    try:
        await live_agents.stop_for_meeting(meeting.id)
    except Exception:
        logger.exception("failed to stop live translation meeting_id=%s", meeting.id)
    try:
        await session_store.release_meeting_slot(meeting.id)
    except Exception:
        logger.exception("failed to release concurrency slot meeting_id=%s", meeting.id)

    await audit_service.record(
        db, actor_type=ActorType.staff, actor_id=staff_id, action="meetings.meeting.delete",
        room=RoomName.meetings, entity_type="meeting", entity_id=meeting.id,
    )
    await db.delete(meeting)
    await db.flush()
