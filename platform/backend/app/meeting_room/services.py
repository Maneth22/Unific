"""Meeting Room state and services not owned by the WhatsApp community
agent: WhatsApp link management, the admin/client conversation viewer,
manual replies, session reports, and video-call meetings. The agent's own
behavior (inbound message handling, auto-reply generation, session state)
lives in `app.agents.whatsapp_community` — this module still owns the
`Conversation`/`Message`/`WhatsAppLink` tables themselves (core relational
data other things reference) and everything that isn't the agent's own
turn-by-turn decision logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.whatsapp_community.session_store import append_turn_if_session_active
from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow, uuid_str
from app.core.providers.base import CommsAgent, ProviderError, VideoProvider, WhatsAppProvider
from app.core.services import audit_service, calendar_service, spend_service
from app.meeting_room import live_translation
from app.meeting_room.models import (
    Conversation,
    ConversationStatus,
    Meeting,
    MeetingInvite,
    MeetingParticipant,
    Message,
    MessageDirection,
    MeetingStatus,
    ReplyMode,
    ReportType,
    SessionReport,
    WhatsAppLink,
)
from app.meeting_room.phone_utils import normalize_phone
from app.profiles.models import ClientOrgProfile, Identity, Permission

logger = logging.getLogger(__name__)

# Kept here (not moved to app.agents.whatsapp_community) since
# send_manual_reply/generate_report — both owned by this module — still
# spend against the same agent_name/cost, for one consistent
# llm_usage/spend ledger regardless of which module actually made the call.
AGENT_NAME = "comms_agent"
OPERATIONAL_COST_PER_REPLY = Decimal("0.01")  # nominal — establishes the spend-tracking pattern
MAX_MESSAGE_LENGTH = 5000


class MeetingRoomError(Exception):
    pass


async def link_phone_number(
    db: AsyncSession, phone_number: str, identity_id: str, *, actor_type: ActorType, actor_id: str | None
) -> WhatsAppLink:
    phone_number = normalize_phone(phone_number)
    existing = await db.execute(select(WhatsAppLink).where(WhatsAppLink.phone_number == phone_number))
    row = existing.scalar_one_or_none()
    before_identity_id = row.identity_id if row else None
    if row is not None:
        row.identity_id = identity_id
    else:
        row = WhatsAppLink(phone_number=phone_number, identity_id=identity_id)
        db.add(row)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="meeting_room.whatsapp_link.set",
        room=RoomName.meeting_room,
        entity_type="whatsapp_link",
        entity_id=row.id,
        before={"identity_id": before_identity_id} if before_identity_id else None,
        after={"phone_number": phone_number, "identity_id": identity_id},
    )
    return row


async def get_or_create_conversation(db: AsyncSession, identity_id: str) -> Conversation:
    result = await db.execute(
        select(Conversation).where(Conversation.identity_id == identity_id, Conversation.status == ConversationStatus.active)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(identity_id=identity_id)
        db.add(conversation)
        await db.flush()
    return conversation


async def initiate_comms_room(
    db: AsyncSession,
    *,
    identity_id: str,
    target_language: str,
    tone: str,
    character_name: str,
    character_role: str,
    actor_type: ActorType,
    actor_id: str | None,
) -> Conversation:
    """Creates (or reconfigures) the active comms room for an identity —
    the initiator hands the agent its language, tone, and character
    ("Jake, a student" / "Mark, a community service worker") before the
    conversation starts. Reconfiguring an existing active room is allowed:
    settings apply from the next message on."""
    identity = await db.get(Identity, identity_id)
    if identity is None:
        raise MeetingRoomError("Identity not found")

    conversation = await get_or_create_conversation(db, identity_id)
    conversation.target_language = (target_language or "auto").strip().lower() or "auto"
    conversation.tone = (tone or "").strip().lower()
    conversation.character_name = (character_name or "").strip()
    conversation.character_role = (character_role or "").strip()
    if actor_type == ActorType.client:
        conversation.initiated_by_client_id = actor_id
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="meeting_room.conversation.initiate",
        room=RoomName.meeting_room,
        entity_type="conversation",
        entity_id=conversation.id,
        after={
            "identity_id": identity_id,
            "target_language": conversation.target_language,
            "tone": conversation.tone,
            "character": f"{conversation.character_name} ({conversation.character_role})".strip(" ()"),
        },
    )
    return conversation


def room_config(conversation: Conversation, perm: Permission) -> dict:
    """The room's effective language/tone/character: conversation-level
    settings (what the initiator chose) win; anything unset falls back to
    the identity's inherited reply config from profiles.permission. Public
    (not `_room_config`) since `app.agents.whatsapp_community.orchestrator`
    needs it too — both this module's own `send_manual_reply`/
    `_outbound_translation`-equivalent flow and the agent's auto-reply flow
    build the same room config."""
    character_name = conversation.character_name or perm.effective_reply_character
    character = f"{character_name}, {conversation.character_role}" if conversation.character_role else character_name
    return {
        "target_language": conversation.target_language or perm.effective_reply_language or "auto",
        "tone": conversation.tone or perm.effective_reply_tone,
        "character": character,
        "role": perm.effective_reply_role,
        "complexity": perm.effective_reply_complexity,
    }


def _build_chat_history(messages: list[Message], max_pairs: int = 4) -> str:
    """The most recent community/client exchange pairs, formatted the way
    the prototype's translation agent expects — used so "auto" language
    can mirror whatever the community member writes in. Only this module's
    own `_outbound_translation` (manual-reply path) still reads Postgres
    `Message` history directly; the agent's own equivalent
    (`app.agents.whatsapp_community.orchestrator._build_chat_history`)
    reads today's turns from Redis instead, since today's `Message` rows
    don't exist yet before flush."""
    lines: list[str] = []
    for msg in messages[-(max_pairs * 4):]:
        if msg.direction == MessageDirection.inbound:
            lines.append(f"[Community]: {msg.original_text}")
        else:
            lines.append(f"[Client]: {msg.final_text or msg.original_text}")
    return "\n".join(lines[-(max_pairs * 2):]) if lines else "No previous conversation."


async def _outbound_translation(
    db: AsyncSession,
    *,
    conversation: Conversation,
    perm: Permission,
    english_text: str,
    comms_agent: CommsAgent,
):
    """English -> the room's configured language/tone/character, with the
    recent chat history so "auto" can mirror the community member's own
    language. Degrades to sending the English untranslated on a provider
    outage — untranslated beats silence. Used only by `send_manual_reply`
    below (a staff/client-initiated reply, always written straight to
    Postgres, unlike the agent's own auto-reply path). Known limitation:
    since today's auto-reply turns live in Redis until end-of-day flush
    (see app.agents.whatsapp_community.session_store), a manual reply sent
    the same day as unflushed auto-reply activity won't see that activity
    in its chat_history context here — it only sees Postgres history from
    prior flushes. Degrades gracefully (less context, not broken); revisit
    if this proves to matter in practice."""
    from app.core.providers.base import OutboundTranslation

    config = room_config(conversation, perm)
    recent = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(16)
    )
    history = _build_chat_history(list(reversed(recent.scalars().all())))

    try:
        return await comms_agent.translate_outbound(
            db,
            english_text,
            chat_history=history,
            target_language=config["target_language"],
            tone=config["tone"],
            character=config["character"],
            identity_id=conversation.identity_id,
            room=RoomName.meeting_room,
            agent_name=AGENT_NAME,
        )
    except ProviderError as exc:
        logger.warning("Outbound translation failed — sending untranslated English: %s", exc)
        return OutboundTranslation(translated_text=english_text, key_points=[], english_preview=english_text)


async def send_manual_reply(
    db: AsyncSession,
    *,
    conversation_id: str,
    text: str,
    actor_type: ActorType,
    actor_id: str | None,
    comms_agent: CommsAgent,
    whatsapp_provider: WhatsAppProvider,
) -> Message:
    if len(text) > MAX_MESSAGE_LENGTH:
        raise MeetingRoomError(f"Message too long (max {MAX_MESSAGE_LENGTH} characters)")
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise MeetingRoomError("Conversation not found")
    perm = await db.get(Permission, conversation.identity_id)
    link_result = await db.execute(select(WhatsAppLink).where(WhatsAppLink.identity_id == conversation.identity_id))
    link = link_result.scalar_one_or_none()
    if link is None:
        raise MeetingRoomError("No WhatsApp number linked to this conversation")

    translation = await _outbound_translation(
        db, conversation=conversation, perm=perm, english_text=text, comms_agent=comms_agent
    )

    try:
        provider_id = await whatsapp_provider.send_message(link.phone_number, translation.translated_text)
    except ProviderError:
        provider_id = ""

    outbound = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.outbound,
        mode=ReplyMode.manual,
        original_text=text,
        translated_text=translation.translated_text,
        final_text=translation.translated_text,
        key_points=translation.key_points,
        sent_by_staff_id=actor_id if actor_type == ActorType.staff else None,
        provider_message_id=provider_id,
    )
    db.add(outbound)
    # Best-effort mirror into today's live Redis session (if the agent has
    # one for this identity) so a same-day auto-reply's chat history
    # doesn't miss a manual reply that happened in between — a Redis
    # outage here must never break manual replies themselves.
    # already_persisted=True tells flush_service this turn is context-only:
    # the Message row above is already committed to Postgres directly by
    # this function, so flush must never re-insert it from Redis too.
    try:
        await append_turn_if_session_active(
            conversation.identity_id,
            {
                "direction": "outbound",
                "mode": "manual",
                "original_text": text,
                "translated_text": translation.translated_text,
                "final_text": translation.translated_text,
                "key_points": translation.key_points,
                "provider_message_id": provider_id,
                "already_persisted": True,
            },
        )
    except Exception:
        logger.warning("Failed to mirror manual reply into the live Redis session (non-fatal)", exc_info=True)
    await spend_service.record_spend(
        db, room=RoomName.meeting_room, agent_name=AGENT_NAME, amount=OPERATIONAL_COST_PER_REPLY, description="Manual reply (translated)"
    )
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="meeting_room.message.manual_reply",
        room=RoomName.meeting_room,
        entity_type="message",
        entity_id=str(outbound.id) if outbound.id else None,
    )
    await db.flush()
    return outbound


# --- Reports (session summary & satisfaction analysis) ---

def _build_transcript(messages: list[Message]) -> str:
    """The full session in the format the report prompts expect: raw
    community text with the agent's clarification and tone insight, and
    the client's English draft with what was actually sent."""
    lines: list[str] = []
    for msg in messages:
        if msg.direction == MessageDirection.inbound:
            lines.append(f"[Community]: {msg.original_text}")
            if msg.translated_text:
                lines.append(f"[Clarification]: {msg.translated_text}")
            insight = (msg.tone_analysis or {}).get("brief_insight")
            if insight:
                lines.append(f"[Tone]: {insight}")
        else:
            lines.append(f"[Client]: {msg.original_text or msg.final_text}")
            if msg.translated_text and msg.translated_text != msg.original_text:
                lines.append(f"[Sent as]: {msg.translated_text}")
    return "\n".join(lines)


async def generate_report(
    db: AsyncSession,
    *,
    conversation_id: str,
    report_type: ReportType,
    comms_agent: CommsAgent,
    actor_type: ActorType,
    actor_id: str | None,
) -> SessionReport:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise MeetingRoomError("Conversation not found")

    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    if not messages:
        raise MeetingRoomError("No messages in this conversation yet — nothing to analyze")

    transcript = _build_transcript(messages)
    if report_type == ReportType.session_summary:
        content = await comms_agent.generate_session_report(
            db, transcript, identity_id=conversation.identity_id, room=RoomName.meeting_room, agent_name=AGENT_NAME
        )
    elif report_type == ReportType.satisfaction_analysis:
        content = await comms_agent.generate_satisfaction_analysis(
            db, transcript, identity_id=conversation.identity_id, room=RoomName.meeting_room, agent_name=AGENT_NAME
        )
    else:
        content = await comms_agent.generate_member_summary(
            db, transcript, identity_id=conversation.identity_id, room=RoomName.meeting_room, agent_name=AGENT_NAME
        )

    report = SessionReport(
        conversation_id=conversation_id,
        report_type=report_type,
        content=content,
        message_count=len(messages),
        generated_by_client_id=actor_id if actor_type == ActorType.client else None,
        generated_by_staff_id=actor_id if actor_type == ActorType.staff else None,
    )
    db.add(report)
    await spend_service.record_spend(
        db, room=RoomName.meeting_room, agent_name=AGENT_NAME, amount=OPERATIONAL_COST_PER_REPLY,
        description=f"Report: {report_type.value}",
    )
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action=f"meeting_room.report.{report_type.value}",
        room=RoomName.meeting_room,
        entity_type="session_report",
        entity_id=report.id,
        after={"conversation_id": conversation_id, "message_count": len(messages)},
    )
    return report


async def list_reports(db: AsyncSession, conversation_id: str) -> list[SessionReport]:
    result = await db.execute(
        select(SessionReport)
        .where(SessionReport.conversation_id == conversation_id)
        .order_by(SessionReport.created_at.desc())
    )
    return list(result.scalars().all())


async def list_conversations(db: AsyncSession) -> list[Conversation]:
    result = await db.execute(select(Conversation).order_by(Conversation.updated_at.desc()))
    return list(result.scalars().all())


async def get_conversation_with_messages(db: AsyncSession, conversation_id: str) -> Conversation | None:
    return await db.get(Conversation, conversation_id)


# --- Meetings ---

_JOINABLE_STATUSES = (MeetingStatus.scheduled, MeetingStatus.live)


async def _send_whatsapp_meeting_invites(
    db: AsyncSession,
    pending_invites: list[tuple[str, MeetingInvite]],
    *,
    scheduled_at: datetime,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    """Best-effort — a send failure, or an identity with no linked
    WhatsApp number at all (a meeting's host can legitimately be a
    group/org-root identity, never phone-linked), must never block
    scheduling itself. No Message/Conversation row is created for this —
    it's a one-off transactional notification, not a conversational turn,
    and would otherwise pollute _build_chat_history's context for the
    community agent's later replies to the same person. No translation
    either for the same reason: that's the _auto_reply conversation
    pipeline's job, not this one."""
    if not pending_invites:
        return
    identity_ids = [identity_id for identity_id, _ in pending_invites]
    result = await db.execute(select(WhatsAppLink).where(WhatsAppLink.identity_id.in_(identity_ids)))
    phone_by_identity = {link.identity_id: link.phone_number for link in result.scalars().all()}
    for identity_id, invite in pending_invites:
        phone_number = phone_by_identity.get(identity_id)
        if not phone_number:
            continue  # e.g. a group/org-root host — nothing to send to
        url = f"{settings.frontend_base_url.rstrip('/')}/meeting-room/join/{invite.token}"
        text = f"You've been invited to a meeting on {scheduled_at.strftime('%b %d, %Y at %H:%M UTC')}. Join here: {url}"
        try:
            await whatsapp_provider.send_message(phone_number, text)
            logger.info("WhatsApp meeting invite sent identity=%s", identity_id)
        except ProviderError:
            logger.warning("Failed to send WhatsApp meeting invite identity=%s", identity_id)


async def schedule_meeting(
    db: AsyncSession,
    *,
    host_identity_id: str,
    scheduled_at: datetime,
    translate_live: bool,
    staff_id: str | None = None,
    client_id: str | None = None,
    notes: str = "",
    participant_identity_ids: list[str] | None = None,
    staff_participant_ids: list[str] | None = None,
    meeting_kind: str = "community",
    video_provider: VideoProvider,
    whatsapp_provider: WhatsAppProvider,
) -> Meeting:
    """Creates the meeting row, its LiveKit room, and a MeetingParticipant
    (+ MeetingInvite, for identity-side participants) for the host, the
    scheduling staff member, and everyone else listed. A room-creation
    failure aborts scheduling entirely — unlike the comms pipeline's
    degrade-gracefully philosophy, a meeting with no room is useless.

    `meeting_kind="client_org"` is the admin "meet with a client" picker —
    every identity participant must be a client-org root (have a
    `ClientOrgProfile`), never an ILC/community identity. `"staff"` and
    `"community"` (the default — the client's own meetings with their
    community, unaffected by this restriction) skip the check.

    Exactly one of `staff_id` (an admin scheduling) or `client_id` (a
    client scheduling a meeting for their own community, `meeting_kind=
    "community"` only) is set — that caller becomes the audit/calendar
    actor; `staff_id` alone still becomes `Meeting.created_by` and an
    invited-staff participant, since that column/relation is staff-only."""
    actor_type = ActorType.staff if staff_id else ActorType.client
    actor_id = staff_id or client_id
    if meeting_kind == "client_org":
        all_identity_ids = {host_identity_id, *(participant_identity_ids or [])} - {None}
        if all_identity_ids:
            result = await db.execute(
                select(ClientOrgProfile.identity_id).where(ClientOrgProfile.identity_id.in_(all_identity_ids))
            )
            org_identity_ids = {row[0] for row in result.all()}
            if org_identity_ids != all_identity_ids:
                raise MeetingRoomError(
                    "A client meeting can only include client organizations, never an ILC/community identity"
                )

    if scheduled_at.tzinfo is not None:
        # Every datetime column in this app is naive UTC (see
        # `core.models.common.utcnow`) — a request body's ISO-8601 string
        # (e.g. from `Date.toISOString()`) parses to a tz-aware datetime,
        # so it has to be normalized here at the service boundary before
        # it ever reaches asyncpg, which rejects aware values for a
        # TIMESTAMP WITHOUT TIME ZONE column.
        scheduled_at = scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)
    meeting_id = uuid_str()
    room_name = f"meeting-{meeting_id}"
    try:
        await video_provider.create_room(room_name)
    except ProviderError as exc:
        raise MeetingRoomError(f"Could not create the video conferencing room: {exc}") from exc

    meeting = Meeting(
        id=meeting_id,
        host_identity_id=host_identity_id,
        scheduled_at=scheduled_at,
        translate_live=translate_live,
        notes=notes,
        created_by=staff_id,
        room_name=room_name,
    )
    db.add(meeting)
    await db.flush()

    # The scheduling staff member (if any — a client-scheduled meeting has
    # none unless explicitly invited) is a participant; the host identity
    # is always a participant too (both dedup via set()).
    for sid in {staff_id, *(staff_participant_ids or [])} - {None}:
        db.add(MeetingParticipant(meeting_id=meeting.id, staff_user_id=sid))

    invite_expires_at = scheduled_at + timedelta(hours=settings.meeting_invite_ttl_hours)
    # host_identity_id is None for a "staff" meeting_kind (no identity-tree
    # node to host it) — only real identity ids become identity-side
    # participants/invites; the host is still a participant via the
    # staff_participant_ids loop above in that case.
    pending_invites: list[tuple[str, MeetingInvite]] = []
    for identity_id in {host_identity_id, *(participant_identity_ids or [])} - {None}:
        participant = MeetingParticipant(meeting_id=meeting.id, identity_id=identity_id)
        db.add(participant)
        await db.flush()
        invite = MeetingInvite(meeting_id=meeting.id, participant_id=participant.id, expires_at=invite_expires_at)
        db.add(invite)
        pending_invites.append((identity_id, invite))
    await db.flush()

    await _send_whatsapp_meeting_invites(
        db, pending_invites, scheduled_at=scheduled_at, whatsapp_provider=whatsapp_provider
    )

    await calendar_service.submit_timing(
        db,
        room=RoomName.meeting_room,
        kind="meeting",
        title=f"Meeting — {host_identity_id}" if host_identity_id else "Staff meeting",
        due_at=scheduled_at,
        related_entity_type="meeting",
        related_entity_id=meeting.id,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="meeting_room.meeting.schedule",
        room=RoomName.meeting_room,
        entity_type="meeting",
        entity_id=meeting.id,
    )
    return meeting


async def list_meetings(db: AsyncSession) -> list[Meeting]:
    result = await db.execute(select(Meeting).order_by(Meeting.scheduled_at))
    return list(result.scalars().all())


async def get_meeting_with_participants(db: AsyncSession, meeting_id: str) -> Meeting | None:
    result = await db.execute(
        select(Meeting).options(selectinload(Meeting.participants)).where(Meeting.id == meeting_id)
    )
    return result.scalar_one_or_none()


async def get_invites_for_meeting(db: AsyncSession, meeting_id: str) -> list[MeetingInvite]:
    result = await db.execute(select(MeetingInvite).where(MeetingInvite.meeting_id == meeting_id))
    return list(result.scalars().all())


async def list_staff_meetings(db: AsyncSession, staff_id: str) -> list[Meeting]:
    """Meetings where this staff account is a participant — invited at
    scheduling time (see `schedule_meeting`'s `staff_participant_ids`) or
    added on first join (see `mint_staff_join`). Mirrors
    `list_client_meetings`'s shape for the client dashboard."""
    result = await db.execute(
        select(Meeting)
        .join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
        .where(MeetingParticipant.staff_user_id == staff_id)
        .order_by(Meeting.scheduled_at.desc())
        .distinct()
    )
    return list(result.scalars().all())


async def list_client_meetings(db: AsyncSession, identity_ids: list[str]) -> list[Meeting]:
    """Meetings where any of the caller's own-or-descendant identities is
    a participant — the client-dashboard scope boundary, same shape as
    every other client list query in this app."""
    result = await db.execute(
        select(Meeting)
        .join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
        .where(MeetingParticipant.identity_id.in_(identity_ids))
        .order_by(Meeting.scheduled_at.desc())
        .distinct()
    )
    return list(result.scalars().all())


async def get_invite_by_token(db: AsyncSession, token: str) -> MeetingInvite | None:
    result = await db.execute(select(MeetingInvite).where(MeetingInvite.token == token))
    invite = result.scalar_one_or_none()
    if invite is None or not invite.is_active or invite.revoked_at is not None:
        return None
    if invite.expires_at < utcnow():
        return None
    return invite


async def get_public_join_info(db: AsyncSession, token: str) -> tuple[Meeting, MeetingParticipant, Identity | None] | None:
    invite = await get_invite_by_token(db, token)
    if invite is None:
        return None
    participant = await db.get(MeetingParticipant, invite.participant_id)
    meeting = await db.get(Meeting, invite.meeting_id)
    if participant is None or meeting is None:
        return None
    identity = await db.get(Identity, participant.identity_id) if participant.identity_id else None
    return meeting, participant, identity


async def _mark_joined(
    db: AsyncSession, *, meeting: Meeting, participant: MeetingParticipant, actor_type: ActorType, actor_id: str | None
) -> None:
    now = utcnow()
    participant.joined_at = now
    if meeting.status == MeetingStatus.scheduled:
        meeting.status = MeetingStatus.live
        meeting.started_at = now
        if meeting.translate_live:
            # Best-effort, same philosophy as the LiveKit room calls below —
            # a translation-agent startup failure shouldn't block the first
            # participant from actually joining the call.
            try:
                await live_translation.start_for_meeting(room_name=meeting.room_name, meeting_id=meeting.id)
            except Exception:
                logger.exception("failed to start live translation meeting_id=%s", meeting.id)
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="meeting_room.meeting.join",
        room=RoomName.meeting_room,
        entity_type="meeting",
        entity_id=meeting.id,
    )
    await db.flush()


def _assert_joinable(meeting: Meeting) -> None:
    if meeting.status not in _JOINABLE_STATUSES:
        raise MeetingRoomError(f"This meeting is {meeting.status.value} and can no longer be joined")


async def mint_staff_join(
    db: AsyncSession, *, meeting_id: str, staff_id: str, staff_name: str, video_provider: VideoProvider
) -> tuple[Meeting, str]:
    """Staff can join any meeting — mirrors the rest of this app's model
    where every active staff account has full access (see
    `app.core.security.dependencies.require_admin`); a staff member not
    originally invited is simply added as a participant on first join."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise MeetingRoomError("Meeting not found")
    _assert_joinable(meeting)

    result = await db.execute(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.staff_user_id == staff_id
        )
    )
    participant = result.scalar_one_or_none()
    if participant is None:
        participant = MeetingParticipant(meeting_id=meeting_id, staff_user_id=staff_id)
        db.add(participant)
        await db.flush()

    token = await video_provider.generate_access_token(
        room_name=meeting.room_name,
        participant_identity=f"staff:{staff_id}",
        participant_name=staff_name,
        ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.staff, actor_id=staff_id)
    return meeting, token


async def mint_client_join(
    db: AsyncSession, *, meeting_id: str, identity_id: str, video_provider: VideoProvider
) -> tuple[Meeting, str]:
    """`identity_id` must already be scope-checked by the caller (router)
    against the client's own subtree — this only checks it's actually a
    participant on this specific meeting."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise MeetingRoomError("Meeting not found")
    _assert_joinable(meeting)

    identity = await db.get(Identity, identity_id)
    if identity is None:
        raise MeetingRoomError("Identity not found")

    result = await db.execute(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.identity_id == identity_id
        )
    )
    participant = result.scalar_one_or_none()
    if participant is None:
        raise MeetingRoomError("This identity is not a participant on this meeting")

    token = await video_provider.generate_access_token(
        room_name=meeting.room_name,
        participant_identity=f"identity:{identity_id}",
        participant_name=identity.name,
        ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.client, actor_id=identity_id)
    return meeting, token


async def mint_public_join(db: AsyncSession, *, token: str, video_provider: VideoProvider) -> tuple[Meeting, str]:
    """The passwordless join path for a WhatsApp-only community member (or
    anyone else holding a valid, unexpired, unrevoked invite link) — the
    token itself is the join credential, no login required."""
    info = await get_public_join_info(db, token)
    if info is None:
        raise MeetingRoomError("This meeting link is invalid or has expired")
    meeting, participant, identity = info
    _assert_joinable(meeting)

    participant_name = identity.name if identity is not None else "Guest"
    token_jwt = await video_provider.generate_access_token(
        room_name=meeting.room_name,
        participant_identity=f"identity:{participant.identity_id}",
        participant_name=participant_name,
        ttl_seconds=settings.meeting_token_ttl_minutes * 60,
    )

    invite = await get_invite_by_token(db, token)
    if invite is not None:
        invite.used_at = utcnow()
    await _mark_joined(db, meeting=meeting, participant=participant, actor_type=ActorType.system, actor_id=None)
    return meeting, token_jwt


async def end_meeting(
    db: AsyncSession,
    *,
    meeting_id: str,
    video_provider: VideoProvider,
    staff_id: str | None = None,
    client_id: str | None = None,
) -> Meeting:
    """Exactly one of `staff_id` (admin) or `client_id` (the client closing
    a meeting they scheduled for their own community) identifies the actor
    for the audit trail."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise MeetingRoomError("Meeting not found")
    if meeting.status == MeetingStatus.cancelled:
        raise MeetingRoomError("This meeting was cancelled")

    try:
        await video_provider.end_room(meeting.room_name)
    except ProviderError as exc:
        # Best-effort: our own record of "this meeting is over" shouldn't
        # hinge on the provider's disconnect call succeeding.
        logger.warning("LiveKit room end failed (marking meeting completed regardless): %s", exc)
    try:
        await live_translation.stop_for_meeting(meeting.id)
    except Exception:
        logger.exception("failed to stop live translation meeting_id=%s", meeting.id)

    meeting.status = MeetingStatus.completed
    meeting.ended_at = utcnow()
    await audit_service.record(
        db,
        actor_type=ActorType.staff if staff_id else ActorType.client,
        actor_id=staff_id or client_id,
        action="meeting_room.meeting.end",
        room=RoomName.meeting_room,
        entity_type="meeting",
        entity_id=meeting.id,
    )
    await db.flush()
    return meeting


async def delete_meeting(db: AsyncSession, *, meeting_id: str, staff_id: str, video_provider: VideoProvider) -> None:
    """Removes a meeting entirely — including force-closing its LiveKit
    room first, so a scheduled-but-abandoned or forgotten-to-end meeting
    doesn't just sit there consuming a room indefinitely. Safe to hard-
    delete (unlike e.g. GroupInvite, which this app deliberately never
    hard-deletes): `AuditLog.entity_id` is a plain string, not a foreign
    key, so the audit trail below survives this row's removal regardless
    of MeetingParticipant/MeetingInvite cascading away with it."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise MeetingRoomError("Meeting not found")

    try:
        await video_provider.end_room(meeting.room_name)
    except ProviderError as exc:
        # Best-effort, same as end_meeting: deletion must not hinge on the
        # provider call succeeding, but we still want to have tried.
        logger.warning("LiveKit room deletion failed (deleting the meeting record regardless): %s", exc)
    try:
        await live_translation.stop_for_meeting(meeting.id)
    except Exception:
        logger.exception("failed to stop live translation meeting_id=%s", meeting.id)

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="meeting_room.meeting.delete",
        room=RoomName.meeting_room,
        entity_type="meeting",
        entity_id=meeting.id,
        before={"room_name": meeting.room_name, "status": meeting.status.value, "scheduled_at": meeting.scheduled_at.isoformat()},
    )
    await db.delete(meeting)
    await db.flush()
