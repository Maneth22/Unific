"""The WhatsApp community agent's entry point. An inbound message arrives
from the webhook (`app.meeting_room.router.inbound_webhook`) -> Profiles
gate check -> comms agent (clarify inbound / analyze tone) -> reply
generator + outbound translation -> WhatsApp send. Session state (recent
turns, today's token spend, today's auto-reply count) lives in Redis via
`session_store`, not Postgres — `app.agents.whatsapp_community.
flush_service` moves it to Postgres `Conversation`/`Message` rows once, at
end of day (or on-demand via the admin flush route).

Two things stay real-time Postgres writes even though message *content*
is batched to Redis: `gate_service.check_and_charge` and
`spend_service.record_spend`. The financial ledger must never be
deferrable — batching it would let the daily/credit caps be bypassed by a
crash between "reply sent" and "flushed to Postgres."

The 1.5k-token session cap (`settings.whatsapp_session_token_cap`) is a
hard block, not a degrade: once an identity's cumulative same-day Gemini
token spend reaches the cap, every further Gemini call for the rest of the
UTC day is skipped outright (not just cheapened) and a fixed, unbilled
`SESSION_LIMIT_REPLY` is sent instead — satisfying a cost cap with a
cheaper-but-still-billed call would defeat its purpose.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.whatsapp_community import session_store
from app.agents.whatsapp_community.providers.stub_reply_generator import FALLBACK_REPLY
from app.config import settings
from app.core.models.archive import ArchiveItemStatus, ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.common import RoomName
from app.core.models.tools import ToolSlot
from app.core.providers.base import CommsAgent, OutboundTranslation, ProviderError, ReplyGenerator, WhatsAppProvider
from app.core.services import archive_service, audit_service, gate_service, spend_service, tools_service
from app.meeting_room import services as meeting_room_services
from app.meeting_room.models import Conversation, WhatsAppLink
from app.meeting_room.phone_utils import normalize_phone
from app.profiles.models import Identity, Permission

logger = logging.getLogger(__name__)

# Unchanged from the pre-move `meeting_room.services` module — renaming
# would fragment historical llm_usage/spend/audit records grouped by this
# string (see the WhatsApp Agents Platform plan's RoomName/agent_name
# stability note).
AGENT_NAME = "comms_agent"
REPLY_COST = Decimal("0")  # the base Meeting Room reply is UNIFIC's free-to-near-free running cost
OPERATIONAL_COST_PER_REPLY = Decimal("0.01")  # nominal — establishes the spend-tracking pattern

SESSION_LIMIT_REPLY = (
    "You've reached today's chat limit for this conversation — a team member will follow up with you."
)


class Bounced(Exception):
    """Raised (and caught by the caller) when an inbound message is
    intentionally not processed further — unregistered sender, or a
    provider failure on send. Distinct from MeetingRoomError, which is
    a caller-facing 4xx-shaped problem."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class InboundResult:
    """What the webhook route reports back per parsed message — replaces
    the old ORM `Message` row return value, since no Postgres row exists
    for a same-day message until flush."""

    identity_id: str
    bounced: bool = False
    reason: str | None = None


def _build_chat_history(turns: list[dict], max_pairs: int = 4) -> str:
    """Same formatting the pre-move `_build_chat_history` produced, now
    reading Redis turn dicts (`{"direction", "original_text", "final_text",
    ...}`) instead of ORM `Message` rows."""
    lines: list[str] = []
    for turn in turns[-(max_pairs * 4):]:
        if turn.get("direction") == "inbound":
            lines.append(f"[Community]: {turn.get('original_text', '')}")
        else:
            lines.append(f"[Client]: {turn.get('final_text') or turn.get('original_text', '')}")
    return "\n".join(lines[-(max_pairs * 2):]) if lines else "No previous conversation."


async def _approved_context(db: AsyncSession, limit: int = 5) -> list[str]:
    """Unchanged from the pre-move implementation — still the Archive
    Locker's text locker. Phase 2 replaces this with a real per-client RAG
    lookup and removes the Archive Locker in the same change; kept as-is
    here so there is never a window with zero context capability."""
    items = await archive_service.list_shelf(db, RoomName.meeting_room, ArchiveShelf.operational_library)
    approved = [i for i in items if i.approved_for_auto_reply and i.status == ArchiveItemStatus.active]
    snippets = []
    for item in approved[:limit]:
        text = item.content.get("text") if isinstance(item.content, dict) else None
        snippets.append(text or item.description or item.title)
    return snippets


async def under_daily_reply_cap(identity_id: str, perm: Permission) -> bool:
    """Whether this identity still has auto-reply budget left today.
    Reimplemented against `session_store`'s Redis counter instead of the
    old Postgres `COUNT(Message)` query — today's Message rows don't exist
    yet (they're only written at flush), so the old query would silently
    always return 0 and never actually cap anything once writes deferred."""
    if perm.effective_daily_reply_cap is None:
        return True
    count = await session_store.get_auto_reply_count(identity_id)
    return count < perm.effective_daily_reply_cap


async def _outbound_translation(
    db: AsyncSession,
    *,
    identity_id: str,
    conversation: Conversation,
    perm: Permission,
    english_text: str,
    comms_agent: CommsAgent,
) -> OutboundTranslation:
    """English -> the room's configured language/tone/character, with
    recent chat history so "auto" can mirror the community member's own
    language. Degrades to sending the English untranslated on a provider
    outage — untranslated beats silence. Chat history now comes from
    Redis (today's turns) instead of a Postgres query."""
    config = meeting_room_services.room_config(conversation, perm)
    turns = await session_store.get_recent_turns(identity_id, limit=16)
    history = _build_chat_history(turns)

    try:
        return await comms_agent.translate_outbound(
            db,
            english_text,
            chat_history=history,
            target_language=config["target_language"],
            tone=config["tone"],
            character=config["character"],
            identity_id=identity_id,
            room=RoomName.meeting_room,
            agent_name=AGENT_NAME,
        )
    except ProviderError as exc:
        logger.warning("Outbound translation failed — sending untranslated English: %s", exc)
        return OutboundTranslation(translated_text=english_text, key_points=[], english_preview=english_text)


async def generate_and_send_reply(
    db: AsyncSession,
    *,
    identity_id: str,
    conversation: Conversation,
    perm: Permission,
    inbound_text: str,
    to_phone: str,
    comms_agent: CommsAgent,
    reply_generator: ReplyGenerator,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    """The auto-reply path (was `meeting_room.services._auto_reply`).
    Turn content lands in Redis via `session_store`, not Postgres, except
    `spend_service.record_spend`, which stays a real-time write — see this
    module's docstring."""
    context = await _approved_context(db)
    config = meeting_room_services.room_config(conversation, perm)
    turns = await session_store.get_recent_turns(identity_id, limit=16)
    chat_history = _build_chat_history(turns)

    try:
        reply_text = await reply_generator.generate_reply(
            db,
            message_text=inbound_text,
            context_snippets=context,
            config=config,
            identity_id=identity_id,
            room=RoomName.meeting_room,
            agent_name=AGENT_NAME,
            chat_history=chat_history,
        )
    except ProviderError as exc:
        logger.warning("Auto-reply generation failed — using fallback reply: %s", exc)
        reply_text = FALLBACK_REPLY  # the LLM is down — still respond with something, not silence

    translation = await _outbound_translation(
        db, identity_id=identity_id, conversation=conversation, perm=perm, english_text=reply_text, comms_agent=comms_agent
    )

    try:
        provider_id = await whatsapp_provider.send_message(to_phone, translation.translated_text)
    except ProviderError:
        provider_id = ""  # logged as sent=False via empty provider_message_id; not fatal to the pipeline

    await session_store.append_turn(
        identity_id,
        {
            "direction": "outbound",
            "mode": "auto",
            "original_text": reply_text,
            "translated_text": translation.translated_text,
            "final_text": translation.translated_text,
            "key_points": translation.key_points,
            "provider_message_id": provider_id,
        },
    )
    await session_store.incr_auto_reply_count(identity_id)
    await spend_service.record_spend(
        db, room=RoomName.meeting_room, agent_name=AGENT_NAME, amount=OPERATIONAL_COST_PER_REPLY, description="Auto reply"
    )


async def receive_inbound_message(
    db: AsyncSession,
    *,
    from_phone: str,
    text: str,
    provider_message_id: str,
    whatsapp_provider: WhatsAppProvider,
) -> InboundResult:
    from_phone = normalize_phone(from_phone)
    link_result = await db.execute(select(WhatsAppLink).where(WhatsAppLink.phone_number == from_phone))
    link = link_result.scalar_one_or_none()
    if link is None:
        raise Bounced(f"No identity linked to {from_phone}")

    identity = await db.get(Identity, link.identity_id)
    perm = await db.get(Permission, link.identity_id)
    if identity is None or perm is None:
        raise Bounced("Linked identity not found")
    if not identity.is_active:
        # Soft-deleted (see profiles.services.deactivate_identity) — same
        # dead-end as an unlinked number, not an error.
        raise Bounced(f"Identity {identity.id} has been deleted")

    # Resolved per-identity (this message's own linked identity), not a
    # caller-supplied singleton — one webhook payload can carry messages
    # for several distinct identities, each with its own effective Tools
    # Registry choice. perm is already loaded above, so this is a plain
    # in-process cache lookup (tools_service.get_tool_instance), no extra
    # query.
    comms_agent: CommsAgent = tools_service.get_tool_instance(ToolSlot.comms_agent, perm.effective_comms_agent_tool)
    reply_generator: ReplyGenerator = tools_service.get_tool_instance(
        ToolSlot.reply_generator, perm.effective_reply_generator_tool
    )

    try:
        await gate_service.check_and_charge(
            db, identity_id=identity.id, room=RoomName.meeting_room, action="receive_message", cost=REPLY_COST
        )
    except gate_service.GateError as exc:
        raise Bounced(str(exc)) from exc

    conversation = await meeting_room_services.get_or_create_conversation(db, identity.id)
    await session_store.ensure_session(
        identity.id, conversation_config=meeting_room_services.room_config(conversation, perm)
    )

    over_token_cap = await session_store.get_token_usage(identity.id) >= settings.whatsapp_session_token_cap

    # Clarify: detect the community member's language and produce the
    # clear-English restatement the client reads. A provider outage must
    # never stop the raw message being logged. Skipped entirely once the
    # session is over its token cap — see this module's docstring.
    detected_lang = ""
    clarification = ""
    tone_analysis: dict = {}
    if not over_token_cap:
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

    await session_store.append_turn(
        identity.id,
        {
            "direction": "inbound",
            "original_text": text,
            "detected_language": detected_lang,
            "translated_text": clarification,
            "tone_analysis": tone_analysis,
            "final_text": text,
            "provider_message_id": provider_message_id,
        },
    )

    await audit_service.record(
        db,
        actor_type=ActorType.system,
        actor_id=None,
        action="meeting_room.message.received",
        room=RoomName.meeting_room,
        entity_type="message",
        entity_id=provider_message_id or None,
        after={"identity_id": identity.id, "from_phone": from_phone},
    )

    if not perm.effective_connected:
        # Passive — the person uses their own phone as normal; the agent
        # logs but does not auto-reply.
        return InboundResult(identity_id=identity.id)

    if over_token_cap:
        if perm.effective_auto_respond:
            try:
                provider_id = await whatsapp_provider.send_message(from_phone, SESSION_LIMIT_REPLY)
            except ProviderError:
                provider_id = ""
            await session_store.append_turn(
                identity.id,
                {
                    "direction": "outbound",
                    "mode": "auto",
                    "original_text": SESSION_LIMIT_REPLY,
                    "translated_text": SESSION_LIMIT_REPLY,
                    "final_text": SESSION_LIMIT_REPLY,
                    "key_points": [],
                    "provider_message_id": provider_id,
                },
            )
        return InboundResult(identity_id=identity.id)

    if perm.effective_auto_respond and await under_daily_reply_cap(identity.id, perm):
        await generate_and_send_reply(
            db,
            identity_id=identity.id,
            conversation=conversation,
            perm=perm,
            inbound_text=clarification or text,
            to_phone=from_phone,
            comms_agent=comms_agent,
            reply_generator=reply_generator,
            whatsapp_provider=whatsapp_provider,
        )
    # else: Manual mode, or daily cap reached — the message waits in the
    # (as-yet-unflushed) conversation for a staff/client manual reply.

    return InboundResult(identity_id=identity.id)
