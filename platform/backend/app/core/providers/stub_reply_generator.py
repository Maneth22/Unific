"""Dev-only reply generator — template-based, deterministic, and hard-
restricted to the context it's given (the Meeting Room's own Shelf 1,
approved_for_auto_reply items only — enforced by the caller, not here).
Never records usage — there's no real spend to track. Swapping in a real
LLM later means implementing `ReplyGenerator`, not touching the pipeline
that assembles `context_snippets`.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName
from app.core.providers.base import ReplyGenerator

FALLBACK_REPLY = "Thanks for your message — a team member will follow up with you soon."


class StubReplyGenerator(ReplyGenerator):
    async def generate_reply(
        self,
        db: AsyncSession,
        *,
        message_text: str,
        context_snippets: list[str],
        config: dict,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> str:
        if not context_snippets:
            return FALLBACK_REPLY
        tone = config.get("tone", "friendly")
        lead = "Here's what I can share: " if tone != "official" else "Please note the following: "
        return lead + " ".join(context_snippets[:2])
