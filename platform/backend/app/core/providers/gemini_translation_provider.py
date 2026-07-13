"""Real translation for the Meeting Room. Adapted from the prototype's
comms_translation_agent prompt (E:\\Unific-Solutions), which was already
tuned for this exact audience — simplify aggressively, preserve every
fact, use natural everyday register rather than formal/literary forms,
and carry the selected tone into the actual wording, not just a label.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.common import RoomName
from app.core.providers.base import TranslationProvider
from app.core.providers.gemini_client import generate
from app.core.services import llm_usage_service

DETECT_LANGUAGE_PROMPT = """Identify the language of the message below. Respond with ONLY a lowercase ISO 639-1 two-letter language code (e.g. "en", "hi", "ta", "si") — no other text."""

TRANSLATE_SYSTEM_TEMPLATE = """You are a translator for a community programme, translating a message into {target_language} for a community member who may have limited formal education.

## Core rules
1. Simplify aggressively: remove sophisticated vocabulary, jargon, and complex sentence structures. Short, direct sentences.
2. Preserve meaning fully: never omit facts, amounts, dates, questions, or conditions. Simplifying is not summarizing.
3. Use natural, everyday spoken register for {target_language} — the way a native speaker actually talks to a neighbour, not a textbook or news-broadcast register.
4. Keep widely-used loanwords (e.g. "bank", "phone") as commonly spoken; don't force-translate them.

## Tone
The selected tone is "{tone}". Make it come through in the actual words and sentence construction:
- "formal": polite, respectful register, still plain and clear — not stiff or bureaucratic.
- "friendly": warm, welcoming, conversational.
- "informal"/other: casual, plain, like talking to a friend.

## Output
Output ONLY the translated text. No quotation marks, no explanation, no English restatement.
"""


class GeminiTranslationProvider(TranslationProvider):
    async def detect_language(
        self, db: AsyncSession, text: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> str:
        result = await generate(
            system_instruction=DETECT_LANGUAGE_PROMPT, user_content=text, temperature=0.0, max_output_tokens=5
        )
        await llm_usage_service.record_usage(
            db,
            room=room,
            agent_name=agent_name,
            identity_id=identity_id,
            provider="gemini",
            model=settings.gemini_model,
            action="language_detection",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            estimated_cost=result.estimated_cost,
        )
        code = result.text.strip().lower()
        return code[:2] if code else "en"

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
        if source_lang and source_lang == target_lang:
            return text
        system_instruction = TRANSLATE_SYSTEM_TEMPLATE.format(target_language=target_lang, tone=tone or "friendly")
        result = await generate(
            system_instruction=system_instruction, user_content=text, temperature=0.3, max_output_tokens=500
        )
        await llm_usage_service.record_usage(
            db,
            room=room,
            agent_name=agent_name,
            identity_id=identity_id,
            provider="gemini",
            model=settings.gemini_model,
            action="translation",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            estimated_cost=result.estimated_cost,
        )
        return result.text or text
