"""End-of-day (or on-demand, via the admin flush route) persistence of
today's WhatsApp community-agent turns from Redis into Postgres
`Conversation`/`Message` rows. Runs on its own `AsyncSessionLocal` (not a
request-scoped session) since it's triggered by the scheduler
(`app.agents.whatsapp_community.scheduler`), not an HTTP request.
"""
from __future__ import annotations

import logging

from app.agents.whatsapp_community import session_store
from app.core.models.audit import ActorType
from app.core.models.common import RoomName
from app.core.services import audit_service
from app.database import AsyncSessionLocal
from app.meeting_room import services as meeting_room_services
from app.meeting_room.models import Message, MessageDirection, ReplyMode

logger = logging.getLogger(__name__)

_MODE_BY_VALUE = {"auto": ReplyMode.auto, "manual": ReplyMode.manual, "adaptive": ReplyMode.adaptive}


def _turn_to_message(conversation_id: str, turn: dict) -> Message:
    direction = MessageDirection.inbound if turn.get("direction") == "inbound" else MessageDirection.outbound
    mode = _MODE_BY_VALUE.get(turn.get("mode") or "")
    return Message(
        conversation_id=conversation_id,
        direction=direction,
        mode=mode,
        original_text=turn.get("original_text", ""),
        detected_language=turn.get("detected_language", ""),
        translated_text=turn.get("translated_text", ""),
        tone_analysis=turn.get("tone_analysis") or {},
        key_points=turn.get("key_points") or [],
        final_text=turn.get("final_text") or turn.get("original_text", ""),
        provider_message_id=turn.get("provider_message_id", ""),
    )


async def flush_identity(identity_id: str) -> int:
    """Flushes one identity's pending turns and returns how many `Message`
    rows were written. Opens its own transaction and only clears the Redis
    session after a successful commit, so a crash mid-batch leaves this
    identity's Redis data intact for the next run — idempotent/resumable
    rather than lossy."""
    async with AsyncSessionLocal() as db:
        turns = await session_store.get_recent_turns(identity_id, limit=None)
        # already_persisted turns (manual replies — see
        # meeting_room.services.send_manual_reply) were written straight to
        # Postgres already; they're in Redis only for chat-history context
        # and must never be re-inserted here.
        pending = [t for t in turns if not t.get("already_persisted")]
        if not pending:
            await session_store.clear_session(identity_id)
            return 0

        conversation = await meeting_room_services.get_or_create_conversation(db, identity_id)
        for turn in pending:
            db.add(_turn_to_message(conversation.id, turn))
        await audit_service.record(
            db,
            actor_type=ActorType.system,
            actor_id=None,
            action="agents.whatsapp_community.session_flush",
            room=RoomName.meeting_room,
            entity_type="conversation",
            entity_id=conversation.id,
            after={"identity_id": identity_id, "turns_flushed": len(pending)},
        )
        await db.commit()

    await session_store.clear_session(identity_id)
    return len(pending)


async def flush_all_sessions() -> dict:
    """Flushes every identity with pending same-day turns. Each identity is
    isolated in its own try/except so one bad identity can't abort the
    whole nightly batch — it's simply left in `wa:pending_flush` for the
    next scheduled run (or a manual retry via the admin flush route)."""
    identity_ids = await session_store.pending_identity_ids()
    flushed = 0
    failed: list[str] = []
    for identity_id in identity_ids:
        try:
            count = await flush_identity(identity_id)
            if count:
                flushed += 1
        except Exception:
            logger.exception("Failed to flush WhatsApp session identity_id=%s", identity_id)
            failed.append(identity_id)
    return {"flushed": flushed, "checked": len(identity_ids), "failed": failed}
