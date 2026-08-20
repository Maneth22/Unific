"""New-pipeline WhatsApp service functions — mirrors
`app.meeting_room.services`'s WhatsApp-adjacent functions, retargeted at
`orgs.Member`/`whatsapp.*` instead of `profiles.Identity`/`meeting_room.*`.
The old module is untouched; nothing here imports from it except the
pure, stateless `normalize_phone` helper.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import RoomName
from app.core.providers.base import CommsAgent, ProviderError, WhatsAppProvider
from app.core.services import audit_service
from app.meeting_room.phone_utils import normalize_phone
from app.orgs.models import Member, Org
from app.whatsapp.models import MessageDirection, PhoneLink, ReplyMode
from app.whatsapp.models import WhatsappConversation as Conversation
from app.whatsapp.models import WhatsappMessage as Message

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096


class WhatsAppError(Exception):
    pass


async def link_phone_number(
    db: AsyncSession, phone_number: str, member_id: str, *, actor_type: ActorType, actor_id: str | None
) -> PhoneLink:
    """Mirrors `app.meeting_room.services.link_phone_number` exactly."""
    phone_number = normalize_phone(phone_number)
    existing = await db.execute(select(PhoneLink).where(PhoneLink.phone_number == phone_number))
    row = existing.scalar_one_or_none()
    before_member_id = row.member_id if row else None
    if row is not None:
        row.member_id = member_id
    else:
        row = PhoneLink(phone_number=phone_number, member_id=member_id)
        db.add(row)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="whatsapp.phone_link.set",
        room=RoomName.whatsapp,
        entity_type="phone_link",
        entity_id=row.id,
        before={"member_id": before_member_id} if before_member_id else None,
        after={"phone_number": phone_number, "member_id": member_id},
    )
    return row


async def get_or_create_conversation(db: AsyncSession, *, member_id: str, org_id: str) -> Conversation:
    result = await db.execute(select(Conversation).where(Conversation.member_id == member_id))
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(member_id=member_id, org_id=org_id)
        db.add(conversation)
        await db.flush()
    return conversation


def room_config(conversation: Conversation) -> dict:
    """Simplified from `meeting_room.services.room_config` — there is no
    `Permission`-equivalent cascade in the flat `orgs` schema yet (no
    per-org reply-role/tone/complexity override mechanism exists), so
    this falls back to fixed defaults for anything the conversation
    itself hasn't set. Flagged as an open question in
    docs/PHASE_2_NOTES.md: whether Org/Group need their own reply-config
    columns later to restore the old cascade's customization."""
    character_name = conversation.character_name or "assistant"
    character = f"{character_name}, {conversation.character_role}" if conversation.character_role else character_name
    return {
        "target_language": conversation.target_language or "auto",
        "tone": conversation.tone or "friendly",
        "character": character,
        "role": "member",
        "complexity": "standard",
    }


async def append_message(
    db: AsyncSession,
    conversation_id: str,
    *,
    direction: MessageDirection,
    mode: ReplyMode | None = None,
    original_text: str = "",
    detected_language: str = "",
    translated_text: str = "",
    final_text: str,
    tone_analysis: dict | None = None,
    key_points: list | None = None,
    sent_by_org_user_id: str | None = None,
    provider_message_id: str = "",
) -> Message:
    """Direct Postgres write — no Redis turn-buffering for the new
    pipeline (see app.whatsapp.session_store's module docstring for why:
    this runs inside an arq job, already off the webhook's synchronous
    request path)."""
    message = Message(
        conversation_id=conversation_id,
        direction=direction,
        mode=mode,
        original_text=original_text,
        detected_language=detected_language,
        translated_text=translated_text,
        final_text=final_text,
        tone_analysis=tone_analysis or {},
        key_points=key_points or [],
        sent_by_org_user_id=sent_by_org_user_id,
        provider_message_id=provider_message_id,
    )
    db.add(message)
    await db.flush()
    return message


async def send_manual_reply(
    db: AsyncSession,
    *,
    conversation_id: str,
    text: str,
    actor_type: ActorType,
    actor_id: str | None,
    whatsapp_provider: WhatsAppProvider,
    comms_agent: CommsAgent,
) -> Message:
    """Mirrors `app.meeting_room.services.send_manual_reply`'s shape,
    simplified: no Redis mirroring (nothing to keep in sync — the new
    pipeline never buffers turns in Redis), no Permission lookup."""
    if len(text) > MAX_MESSAGE_LENGTH:
        raise WhatsAppError(f"Message too long (max {MAX_MESSAGE_LENGTH} characters)")

    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise WhatsAppError("Conversation not found")

    link_result = await db.execute(select(PhoneLink).where(PhoneLink.member_id == conversation.member_id))
    link = link_result.scalar_one_or_none()
    if link is None:
        raise WhatsAppError("No WhatsApp number linked to this conversation")

    config = room_config(conversation)
    try:
        translation = await comms_agent.translate_outbound(
            db, text, chat_history="", target_language=config["target_language"], tone=config["tone"],
            character=config["character"], identity_id=None, member_id=conversation.member_id, room=RoomName.whatsapp,
            agent_name="whatsapp_comms_agent",
        )
        translated_text = translation.translated_text
        key_points = translation.key_points
    except ProviderError as exc:
        logger.warning("Outbound translation failed — sending untranslated English: %s", exc)
        translated_text = text
        key_points = []

    try:
        provider_id = await whatsapp_provider.send_message(link.phone_number, translated_text)
    except ProviderError:
        provider_id = ""

    org_user_id = actor_id if actor_type == ActorType.org_user else None
    message = await append_message(
        db, conversation.id, direction=MessageDirection.outbound, mode=ReplyMode.manual,
        original_text=text, translated_text=translated_text, final_text=translated_text,
        key_points=key_points, sent_by_org_user_id=org_user_id, provider_message_id=provider_id,
    )

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="whatsapp.message.manual_reply",
        room=RoomName.whatsapp,
        entity_type="message",
        entity_id=str(message.id),
        after={"conversation_id": conversation.id},
    )
    return message


async def list_conversations(db: AsyncSession, *, org_id: str | None = None) -> list[Conversation]:
    query = select(Conversation).order_by(Conversation.updated_at.desc())
    if org_id is not None:
        query = query.where(Conversation.org_id == org_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_conversation_with_messages(db: AsyncSession, conversation_id: str) -> Conversation | None:
    return await db.get(Conversation, conversation_id)


async def list_whatsapp_member_directory(db: AsyncSession) -> list[dict]:
    """The admin transparency query — a member name, phone, group, and
    org, in one flat join. Trivial because the `orgs` schema is flat (no
    tree-walking, unlike the old identity tree) — see
    docs/PHASE_2_NOTES.md's "Admin transparency" section for why this
    covers only the NEW pipeline's members for now, with the OLD
    pipeline's WhatsAppLink-linked identities flagged as a named Prompt 5
    fast-follow rather than silently omitted forever."""
    from app.orgs.models import Group

    stmt = (
        select(
            Member.id,
            Member.name,
            Member.is_active,
            Member.group_id,
            Group.name.label("group_name"),
            Member.org_id,
            Org.name.label("org_name"),
            PhoneLink.phone_number,
        )
        .join(Org, Org.id == Member.org_id)
        .outerjoin(Group, Group.id == Member.group_id)
        .outerjoin(PhoneLink, PhoneLink.member_id == Member.id)
        .order_by(Org.name, Group.name, Member.name)
    )
    result = await db.execute(stmt)
    return [
        {
            "member_id": row.id,
            "member_name": row.name,
            "is_active": row.is_active,
            "phone_number": row.phone_number,
            "group_id": row.group_id,
            "group_name": row.group_name,
            "org_id": row.org_id,
            "org_name": row.org_name,
        }
        for row in result.all()
    ]
