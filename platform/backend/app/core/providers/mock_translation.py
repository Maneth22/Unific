"""Dev-only translation provider — deterministic, no external call, and
never records usage (there's no real spend to track). Wiring a real
provider later means implementing this same interface, not touching the
message pipeline.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName
from app.core.providers.base import TranslationProvider


class MockTranslationProvider(TranslationProvider):
    async def detect_language(
        self, db: AsyncSession, text: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> str:
        return "en"

    async def translate(
        self,
        db: AsyncSession,
        text: str,
        *,
        source_lang: str | None,
        target_lang: str,
        tone: str | None = None,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> str:
        if source_lang == target_lang:
            return text
        return f"[{target_lang}] {text}"
