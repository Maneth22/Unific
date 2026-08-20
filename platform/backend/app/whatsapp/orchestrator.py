"""The NEW WhatsApp pipeline's entry point — bound to `orgs.Member`
instead of `profiles.Identity`. Mirrors
`app.agents.whatsapp_community.orchestrator`'s flow/shape closely
(receive -> resolve tools -> per-org spend reserve -> per-member token-
cap check -> clarify/tone (degrade on ProviderError) -> direct Postgres
write -> audit -> reply generation gated on cap+reserve, concurrency-
slot-wrapped send) but runs inside an arq job, not inline in the webhook
request — see `app.whatsapp.session_store`'s module docstring for why
that means no Redis turn-buffering here.

Deliberately simplified per the rebuild directive ("do not port the
character-voice/report-generation complexity yet"): only
clarify_inbound/analyze_tone/translate_outbound/generate_reply are used,
never generate_session_report/generate_satisfaction_analysis/
generate_member_summary. `context_snippets` is always `[]` for v1 — the
old pipeline's `_approved_context` reads the Archive Locker, a
meeting_room-room-scoped concept with no `orgs`-schema equivalent yet
(flagged as an open question in docs/PHASE_2_NOTES.md).

No `Permission`-equivalent cascade exists in the flat `orgs` schema, so
there is no per-member "connected"/"auto_respond"/"daily_reply_cap"
control yet — every active member with a phone_link is treated as
connected + auto-respond + uncapped-per-day (still gated by the
per-member 1500-token/day cap and the new per-org spend cap). Flagged as
an open question for a later phase.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.whatsapp_community import session_store as legacy_session_store
from app.agents.whatsapp_community.orchestrator import SESSION_LIMIT_REPLY  # reuse the exact fixed string, don't duplicate
from app.agents.whatsapp_community.providers.stub_reply_generator import FALLBACK_REPLY
from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.common import RoomName
from app.core.models.tools import ToolSlot
from app.core.providers.base import CommsAgent, OutboundTranslation, ProviderError, ReplyGenerator, WhatsAppProvider
from app.core.services import audit_service, tools_service
from app.meeting_room.phone_utils import normalize_phone
from app.orgs.models import Member
from app.whatsapp import services as whatsapp_services
from app.whatsapp import session_store
from app.whatsapp.models import MessageDirection, PhoneLink, ReplyMode
from app.whatsapp.models import WhatsappMessage as Message

logger = logging.getLogger(__name__)

AGENT_NAME = "whatsapp_comms_agent"  # distinct from the old pipeline's "comms_agent" — separable in llm_usage/agent_run_log


class Bounced(Exception):
    """Same shape as the old pipeline's `Bounced` — raised for an
    unregistered sender or a hard-stop condition, caught by the arq job
    (and, before dispatch, the webhook never even reaches this pipeline
    for a number not in `whatsapp.PhoneLink`)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class InboundResult:
    member_id: str
    bounced: bool = False
    reason: str | None = None


def _build_chat_history(messages: list[Message], max_pairs: int = 4) -> str:
    """Reads ORM rows (this pipeline writes Message directly to Postgres,
    no Redis turn buffer) — same formatting convention as both the old
    pipeline's Redis-turn-based and meeting_room.services's Postgres-row-
    based chat-history builders."""
    lines: list[str] = []
    for msg in messages[-(max_pairs * 4):]:
        if msg.direction == MessageDirection.inbound:
            lines.append(f"[Community]: {msg.original_text}")
        else:
            lines.append(f"[Client]: {msg.final_text or msg.original_text}")
    return "\n".join(lines[-(max_pairs * 2):]) if lines else "No previous conversation."


async def generate_and_send_reply(
    db: AsyncSession,
    *,
    member: Member,
    conversation,
    inbound_text: str,
    to_phone: str,
    comms_agent: CommsAgent,
    reply_generator: ReplyGenerator,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    config = whatsapp_services.room_config(conversation)
    recent = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(16)
    )
    chat_history = _build_chat_history(list(reversed(recent.scalars().all())))

    async with session_store.org_concurrency_slot("llm", member.org_id, limit=settings.max_concurrent_llm_calls_per_org):
        try:
            reply_text = await reply_generator.generate_reply(
                db, message_text=inbound_text, context_snippets=[], config=config,
                identity_id=None, member_id=member.id, room=RoomName.whatsapp, agent_name=AGENT_NAME,
                chat_history=chat_history,
            )
        except ProviderError as exc:
            logger.warning("Auto-reply generation failed — using fallback reply: %s", exc)
            reply_text = FALLBACK_REPLY

        try:
            translation: OutboundTranslation = await comms_agent.translate_outbound(
                db, reply_text, chat_history=chat_history, target_language=config["target_language"],
                tone=config["tone"], character=config["character"], identity_id=None, member_id=member.id,
                room=RoomName.whatsapp, agent_name=AGENT_NAME,
            )
        except ProviderError as exc:
            logger.warning("Outbound translation failed — sending untranslated English: %s", exc)
            translation = OutboundTranslation(translated_text=reply_text, key_points=[], english_preview=reply_text)

    async with session_store.org_concurrency_slot("send", member.org_id, limit=settings.max_concurrent_whatsapp_sends_per_org):
        try:
            provider_id = await whatsapp_provider.send_message(to_phone, translation.translated_text)
        except ProviderError:
            provider_id = ""

    await whatsapp_services.append_message(
        db, conversation.id, direction=MessageDirection.outbound, mode=ReplyMode.auto,
        original_text=reply_text, translated_text=translation.translated_text, final_text=translation.translated_text,
        key_points=translation.key_points, provider_message_id=provider_id,
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
    link_result = await db.execute(select(PhoneLink).where(PhoneLink.phone_number == from_phone))
    link = link_result.scalar_one_or_none()
    if link is None:
        raise Bounced(f"No member linked to {from_phone}")

    member = await db.get(Member, link.member_id)
    if member is None:
        raise Bounced("Linked member not found")
    if not member.is_active:
        raise Bounced(f"Member {member.id} is not active")

    # No per-org Tools Registry override exists yet in the orgs schema —
    # every org shares the same global selection. Flagged as an open
    # question in docs/PHASE_2_NOTES.md for Prompt 4 (plugin entitlements).
    comms_agent: CommsAgent = await tools_service.get_global_tool(db, ToolSlot.comms_agent)
    reply_generator: ReplyGenerator = await tools_service.get_global_tool(db, ToolSlot.reply_generator)

    conversation = await whatsapp_services.get_or_create_conversation(db, member_id=member.id, org_id=member.org_id)

    # Per-org LLM spend cap — reserved BEFORE the Gemini call sequence
    # starts (actual cost is only known after all calls complete).
    reserved = await session_store.reserve_org_spend(
        member.org_id,
        reservation_usd=settings.whatsapp_org_spend_reservation_usd,
        cap_usd=settings.whatsapp_org_daily_llm_spend_cap_usd,
        ttl_seconds=86400,
    )

    # Per-member token cap — the SAME counter the old pipeline's Gemini
    # calls write to (see gemini_reply_generator.py/gemini_comms_agent.py's
    # additive member_id widening) — not a new, disconnected Redis store.
    over_token_cap = await legacy_session_store.get_token_usage(member.id) >= settings.whatsapp_session_token_cap

    detected_lang = ""
    clarification = ""
    tone_analysis: dict = {}
    if reserved and not over_token_cap:
        async with session_store.org_concurrency_slot("llm", member.org_id, limit=settings.max_concurrent_llm_calls_per_org):
            try:
                result = await comms_agent.clarify_inbound(
                    db, text, identity_id=None, member_id=member.id, room=RoomName.whatsapp, agent_name=AGENT_NAME
                )
                detected_lang = result.detected_code
                clarification = result.clarification
                try:
                    tone_analysis = await comms_agent.analyze_tone(
                        db, text, detected_language=result.detected_language, identity_id=None, member_id=member.id,
                        room=RoomName.whatsapp, agent_name=AGENT_NAME,
                    )
                except ProviderError as exc:
                    logger.warning("Tone analysis failed for inbound message: %s", exc)
                    tone_analysis = {}
            except ProviderError as exc:
                logger.warning("Clarification failed for inbound message: %s", exc)
    elif not reserved:
        logger.warning("Org %s over daily LLM spend cap — skipping clarify/tone/reply", member.org_id)

    await whatsapp_services.append_message(
        db, conversation.id, direction=MessageDirection.inbound,
        original_text=text, detected_language=detected_lang, translated_text=clarification,
        tone_analysis=tone_analysis, final_text=text, provider_message_id=provider_message_id,
    )

    await audit_service.record(
        db,
        actor_type=ActorType.system,
        actor_id=None,
        action="whatsapp.message.received",
        room=RoomName.whatsapp,
        entity_type="message",
        entity_id=provider_message_id or None,
        after={"member_id": member.id, "from_phone": from_phone},
    )

    if over_token_cap:
        try:
            provider_id = await whatsapp_provider.send_message(from_phone, SESSION_LIMIT_REPLY)
        except ProviderError:
            provider_id = ""
        await whatsapp_services.append_message(
            db, conversation.id, direction=MessageDirection.outbound, mode=ReplyMode.auto,
            original_text=SESSION_LIMIT_REPLY, translated_text=SESSION_LIMIT_REPLY, final_text=SESSION_LIMIT_REPLY,
            provider_message_id=provider_id,
        )
        return InboundResult(member_id=member.id)

    if reserved:
        await generate_and_send_reply(
            db, member=member, conversation=conversation, inbound_text=clarification or text, to_phone=from_phone,
            comms_agent=comms_agent, reply_generator=reply_generator, whatsapp_provider=whatsapp_provider,
        )
    # else: org is over its daily LLM spend cap — the inbound message is
    # still logged (above) and waits for a manual org-user reply.

    return InboundResult(member_id=member.id)
