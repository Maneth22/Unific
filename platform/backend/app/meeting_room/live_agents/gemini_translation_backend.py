"""The default `LiveTranslationBackend` — exactly what `orchestrator.py`
and `translator.py` did inline before the Tools Registry made this
swappable: a `genai.Client` calling `generate_content` with a system
instruction, optionally in strict JSON response mode.
"""
from __future__ import annotations

import logging

from google import genai
from google.genai import types

from app.config import settings
from app.meeting_room.live_agents.translation_backends import LiveTranslationBackend

logger = logging.getLogger("live_agents.gemini_translation_backend")


class GeminiLiveTranslationBackend(LiveTranslationBackend):
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.live_agents_gemini_model

    async def generate(self, *, text: str, system_instruction: str, json_mode: bool) -> str | None:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json" if json_mode else None,
                ),
            )
            translated = (response.text or "").strip()
            return translated or None
        except Exception:
            logger.exception("Gemini live-translation call failed")
            return None
