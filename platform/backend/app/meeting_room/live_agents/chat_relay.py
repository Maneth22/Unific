"""Translated in-call chat. Listens on the standard `lk.chat` text-stream
topic (the same topic `@livekit/components-react`'s prefab `<Chat>`
component would use, by LiveKit's own convention — this app's frontend now
sends on it directly via a custom `ChatPanel.jsx` instead of the prefab,
see that component) and relays a translated payload per distinct
`chat_language` actually needed, on a separate topic
(`lk.chat.translated`) via `destination_identities` — never a Gemini call
per recipient, always per distinct target language (same
`TranslatorManager`/dedup shape as captions.py).

Every message is persisted (original immediately, each translation as it's
computed) to `MeetingChatMessage` — best-effort, a persistence failure must
never block live relay delivery, matching this codebase's established
philosophy for every other non-core-path write.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from livekit import rtc
from sqlalchemy import select

from app.config import settings
from app.core.models.common import uuid_str
from app.database import AsyncSessionLocal
from app.meeting_room.live_agents.participant_attrs import ParticipantRegistry
from app.meeting_room.live_agents.translator import TranslatorManager
from app.meeting_room.models import MeetingChatMessage

logger = logging.getLogger("live_agents.chat")

CHAT_TOPIC = "lk.chat"
CHAT_TRANSLATED_TOPIC = "lk.chat.translated"


class ChatRelay:
    """One per meeting."""

    def __init__(self, *, room: rtc.Room, meeting_id: str, registry: ParticipantRegistry, translator: TranslatorManager):
        self._room = room
        self._meeting_id = meeting_id
        self._registry = registry
        self._translator = translator
        # Text-stream handlers must be sync (see LiveKit's own docs
        # example) — each incoming message spawns its own task, tracked
        # here only so start()/stop() has something to await/cancel on
        # teardown rather than leaving in-flight relays orphaned.
        self._active_tasks: set[asyncio.Task] = set()

    def start(self) -> None:
        self._room.register_text_stream_handler(CHAT_TOPIC, self._on_stream)

    async def stop(self) -> None:
        try:
            self._room.unregister_text_stream_handler(CHAT_TOPIC)
        except Exception:
            pass
        for task in list(self._active_tasks):
            task.cancel()
        for task in list(self._active_tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def _on_stream(self, reader, participant_identity: str) -> None:
        task = asyncio.create_task(self._handle_message(reader, participant_identity))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def _handle_message(self, reader, sender_identity: str) -> None:
        raw = await reader.read_all()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("malformed chat payload from %s — dropping", sender_identity)
            return

        original_text = str(payload.get("original_text") or "").strip()
        if not original_text:
            return
        message_id = str(payload.get("message_id") or uuid_str())

        # Trust the LiveKit-level sender identity (the transport already
        # verified who actually sent this stream), not the payload's own
        # sender_identity field, for anything security-relevant — the
        # payload field is only ever used for display purposes downstream.
        sender_settings = self._registry.get(sender_identity)
        source_lang = (
            sender_settings.chat_language
            if sender_settings is not None
            else str(payload.get("source_language") or settings.live_agents_default_language)
        )

        await self._persist_original(message_id, sender_identity, original_text, source_lang)

        relay_started_at = time.monotonic()
        grouped = self._registry.chat_recipients_by_language(source_lang=source_lang, exclude_identity=sender_identity)
        for target_lang, recipients in grouped.items():
            if target_lang == source_lang:
                # Already has the original via the room-wide lk.chat
                # broadcast — no Gemini call, no translated payload at all.
                continue
            t0 = time.monotonic()
            translated = await self._translator.translate(
                original_text, source_lang, target_lang, mode=settings.live_agents_chat_translation_mode
            )
            translate_ms = (time.monotonic() - t0) * 1000
            payload_out = {
                "message_id": message_id,
                "sender_identity": sender_identity,
                "original_text": original_text,
                "source_language": source_lang,
                "translated_text": translated,
                "target_language": target_lang,
                "timestamp": time.time(),
            }
            try:
                await self._room.local_participant.send_text(
                    json.dumps(payload_out), topic=CHAT_TRANSLATED_TOPIC, destination_identities=recipients,
                )
            except Exception:
                logger.exception(
                    "failed to send translated chat message_id=%s target_lang=%s", message_id, target_lang
                )
                continue
            await self._persist_translation(message_id, target_lang, translated)
            logger.info(
                "live_agents.chat message_id=%s source_lang=%s target_lang=%s recipients=%d "
                "translate_ms=%d total_ms=%d",
                message_id, source_lang, target_lang, len(recipients),
                translate_ms, (time.monotonic() - relay_started_at) * 1000,
            )

    async def _persist_original(self, message_id: str, sender_identity: str, original_text: str, source_lang: str) -> None:
        try:
            async with AsyncSessionLocal() as db:
                db.add(
                    MeetingChatMessage(
                        meeting_id=self._meeting_id,
                        message_id=message_id,
                        sender_identity=sender_identity,
                        original_text=original_text,
                        source_language=source_lang,
                    )
                )
                await db.commit()
        except Exception:
            # Best-effort — a persistence failure (including a duplicate
            # message_id, which the unique index rejects) must never block
            # live relay delivery.
            logger.exception("failed to persist chat message message_id=%s", message_id)

    async def _persist_translation(self, message_id: str, target_lang: str, translated_text: str) -> None:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(MeetingChatMessage).where(
                        MeetingChatMessage.meeting_id == self._meeting_id,
                        MeetingChatMessage.message_id == message_id,
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return
                # Reassign (not in-place mutate) so SQLAlchemy's change
                # tracking on the JSONB column actually notices the update.
                row.translations = {**row.translations, target_lang: translated_text}
                await db.commit()
        except Exception:
            logger.exception(
                "failed to persist chat translation message_id=%s target_lang=%s", message_id, target_lang
            )
