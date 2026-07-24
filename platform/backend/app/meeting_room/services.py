"""The message pipeline: WhatsApp -> Profiles gate check -> the comms
agent (clarify inbound / translate outbound, in the room's configured
language, tone and character) -> WhatsApp send -> everything logged.
This is the literal implementation of "a message comes in, we find whose
it is, and we answer it" — with the intermediary-agent layer ported from
the prototype so neither side ever hits a language barrier: the community
member reads their own language in the character's voice, the client
reads clear English with tone insights.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.models.archive import ArchiveItemStatus, ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow, uuid_str
from app.core.providers.base import CommsAgent, ProviderError, ReplyGenerator, VideoProvider, WhatsAppProvider
from app.core.providers.stub_reply_generator import FALLBACK_REPLY
from app.core.services import archive_service, audit_service, calendar_service, gate_service, spend_service
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
from app.profiles.models import ClientOrgProfile, Identity, Permission

logger = logging.getLogger(__name__)

AGENT_NAME = "comms_agent"
REPLY_COST = Decimal("0")  # the base Meeting Room reply is UNIFIC's free-to-near-free running cost
OPERATIONAL_COST_PER_REPLY = Decimal("0.01")  # nominal — establishes the spend-tracking pattern
MAX_MESSAGE_LENGTH = 5000


class MeetingRoomError(Exception):
    pass


class Bounced(Exception):
    """Raised (and caught by the caller) when an inbound message is
    intentionally not processed further — unregistered sender, or a
    provider failure on send. Distinct from MeetingRoomError, which is
    a caller-facing 4xx-shaped problem."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def link_phone_number(
    db: AsyncSession, phone_number: str, identity_id: str, *, actor_type: ActorType, actor_id: str | None
) -> WhatsAppLink:
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


async def _get_or_create_conversation(db: AsyncSession, identity_id: str) -> Conversation:
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

    conversation = await _get_or_create_conversation(db, identity_id)
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


def _room_config(conversation: Conversation, perm: Permission) -> dict:
    """The room's effective language/tone/character: conversation-level
    settings (what the initiator chose) win; anything unset falls back to
    the identity's inherited reply config from profiles.permission."""
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
    can mirror whatever the community member writes in."""
    lines: list[str] = []
    for msg in messages[-(max_pairs * 4):]:
        if msg.direction == MessageDirection.inbound:
            lines.append(f"[Community]: {msg.original_text}")
        else:
            lines.append(f"[Client]: {msg.final_text or msg.original_text}")
    return "\n".join(lines[-(max_pairs * 2):]) if lines else "No previous conversation."


async def _approved_context(db: AsyncSession, limit: int = 5) -> list[str]:
    items = await archive_service.list_shelf(db, RoomName.meeting_room, ArchiveShelf.operational_library)
    approved = [i for i in items if i.approved_for_auto_reply and i.status == ArchiveItemStatus.active]
    snippets = []
    for item in approved[:limit]:
        text = item.content.get("text") if isinstance(item.content, dict) else None
        snippets.append(text or item.description or item.title)
    return snippets


async def receive_inbound_message(
    db: AsyncSession,
    *,
    from_phone: str,
    text: str,
    provider_message_id: str,
    comms_agent: CommsAgent,
    reply_generator: ReplyGenerator,
    whatsapp_provider: WhatsAppProvider,
) -> Message:
    link_result = await db.execute(select(WhatsAppLink).where(WhatsAppLink.phone_number == from_phone))
    link = link_result.scalar_one_or_none()
    if link is None:
        raise Bounced(f"No identity linked to {from_phone}")

    identity = await db.get(Identity, link.identity_id)
    perm = await db.get(Permission, link.identity_id)
    if identity is None or perm is None:
        raise Bounced("Linked identity not found")

    try:
        await gate_service.check_and_charge(
            db, identity_id=identity.id, room=RoomName.meeting_room, action="receive_message", cost=REPLY_COST
        )
    except gate_service.GateError as exc:
        raise Bounced(str(exc)) from exc

    conversation = await _get_or_create_conversation(db, identity.id)

    # Clarify: detect the community member's language and produce the
    # clear-English restatement the client reads. A provider outage must
    # never stop the raw message being logged.
    detected_lang = ""
    clarification = ""
    tone_analysis: dict = {}
    try:
        result = await comms_agent.clarify_inbound(
            db, text, identity_id=identity.id, room=RoomName.meeting_room, agent_name=AGENT_NAME
        )
        detected_lang = result.detected_code
        clarification = result.clarification
        try:
            tone_analysis = await comms_agent.analyze_tone(
                db,
                text,
                detected_language=result.detected_language,
                identity_id=identity.id,
                room=RoomName.meeting_room,
                agent_name=AGENT_NAME,
            )
        except ProviderError as exc:
            logger.warning("Tone analysis failed for inbound message: %s", exc)
            tone_analysis = {}
    except ProviderError as exc:
        logger.warning("Clarification failed for inbound message: %s", exc)

    inbound = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.inbound,
        original_text=text,
        detected_language=detected_lang,
        translated_text=clarification,
        tone_analysis=tone_analysis,
        final_text=text,
        provider_message_id=provider_message_id,
    )
    db.add(inbound)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.system,
        actor_id=None,
        action="meeting_room.message.received",
        room=RoomName.meeting_room,
        entity_type="message",
        entity_id=str(inbound.id),
        after={"identity_id": identity.id, "from_phone": from_phone},
    )

    if not perm.effective_connected:
        # Passive — the person uses their own phone as normal; Comms logs
        # but does not auto-reply.
        await db.flush()
        return inbound

    if perm.effective_auto_respond:
        await _auto_reply(
            db,
            conversation=conversation,
            identity=identity,
            perm=perm,
            inbound_text=clarification or text,
            to_phone=from_phone,
            comms_agent=comms_agent,
            reply_generator=reply_generator,
            whatsapp_provider=whatsapp_provider,
        )
    # else: Manual mode — the message waits in the conversation for the
    # client or a staff member to answer via `send_manual_reply`.

    return inbound


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
    outage — untranslated beats silence."""
    from app.core.providers.base import OutboundTranslation

    config = _room_config(conversation, perm)
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


async def _auto_reply(
    db: AsyncSession,
    *,
    conversation: Conversation,
    identity: Identity,
    perm: Permission,
    inbound_text: str,
    to_phone: str,
    comms_agent: CommsAgent,
    reply_generator: ReplyGenerator,
    whatsapp_provider: WhatsAppProvider,
) -> Message:
    context = await _approved_context(db)
    config = _room_config(conversation, perm)
    try:
        reply_text = await reply_generator.generate_reply(
            db,
            message_text=inbound_text,
            context_snippets=context,
            config=config,
            identity_id=identity.id,
            room=RoomName.meeting_room,
            agent_name=AGENT_NAME,
        )
    except ProviderError as exc:
        logger.warning("Auto-reply generation failed — using fallback reply: %s", exc)
        reply_text = FALLBACK_REPLY  # the LLM is down — still respond with something, not silence

    translation = await _outbound_translation(
        db, conversation=conversation, perm=perm, english_text=reply_text, comms_agent=comms_agent
    )

    try:
        provider_id = await whatsapp_provider.send_message(to_phone, translation.translated_text)
    except ProviderError:
        provider_id = ""  # logged as sent=False via empty provider_message_id; not fatal to the pipeline

    outbound = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.outbound,
        mode=ReplyMode.auto,
        original_text=reply_text,
        translated_text=translation.translated_text,
        final_text=translation.translated_text,
        key_points=translation.key_points,
        provider_message_id=provider_id,
    )
    db.add(outbound)
    await spend_service.record_spend(
        db, room=RoomName.meeting_room, agent_name=AGENT_NAME, amount=OPERATIONAL_COST_PER_REPLY, description="Auto reply"
    )
    await db.flush()
    return outbound


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


async def schedule_meeting(
    db: AsyncSession,
    *,
    host_identity_id: str,
    scheduled_at: datetime,
    translate_live: bool,
    staff_id: str,
    notes: str = "",
    participant_identity_ids: list[str] | None = None,
    staff_participant_ids: list[str] | None = None,
    meeting_kind: str = "community",
    video_provider: VideoProvider,
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
    community, unaffected by this restriction) skip the check."""
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

    # The scheduling staff member is always a participant; the host
    # identity is always a participant too (both dedup via set()).
    for sid in {staff_id, *(staff_participant_ids or [])}:
        db.add(MeetingParticipant(meeting_id=meeting.id, staff_user_id=sid))

    invite_expires_at = scheduled_at + timedelta(hours=settings.meeting_invite_ttl_hours)
    # host_identity_id is None for a "staff" meeting_kind (no identity-tree
    # node to host it) — only real identity ids become identity-side
    # participants/invites; the host is still a participant via the
    # staff_participant_ids loop above in that case.
    for identity_id in {host_identity_id, *(participant_identity_ids or [])} - {None}:
        participant = MeetingParticipant(meeting_id=meeting.id, identity_id=identity_id)
        db.add(participant)
        await db.flush()
        db.add(MeetingInvite(meeting_id=meeting.id, participant_id=participant.id, expires_at=invite_expires_at))
    await db.flush()

    await calendar_service.submit_timing(
        db,
        room=RoomName.meeting_room,
        kind="meeting",
        title=f"Meeting — {host_identity_id}" if host_identity_id else "Staff meeting",
        due_at=scheduled_at,
        related_entity_type="meeting",
        related_entity_id=meeting.id,
        actor_type=ActorType.staff,
        actor_id=staff_id,
    )
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
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


async def end_meeting(db: AsyncSession, *, meeting_id: str, staff_id: str, video_provider: VideoProvider) -> Meeting:
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

    meeting.status = MeetingStatus.completed
    meeting.ended_at = utcnow()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
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
