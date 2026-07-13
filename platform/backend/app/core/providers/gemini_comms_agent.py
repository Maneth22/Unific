"""The real (Gemini-backed) comms agent — the prototype's four comms-room
agents plus the new satisfaction analysis, all running the templates in
`comms_prompts.py`. Every call records its token usage against the
identity whose conversation triggered it.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.config import settings
from app.core.models.common import RoomName
from app.core.providers import comms_prompts
from app.core.providers.base import CommsAgent, InboundClarification, OutboundTranslation, ProviderError
from app.core.providers.gemini_client import GeminiResult, generate, parse_json_block
from app.core.services import llm_usage_service


class GeminiCommsAgent(CommsAgent):
    async def _call(
        self,
        db: AsyncSession,
        *,
        prompt: str,
        action: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
        max_output_tokens: int,
        temperature: float = 0.3,
    ) -> dict:
        result: GeminiResult = await generate(
            system_instruction="You are a precise agent that outputs only raw JSON objects, never markdown fences or commentary.",
            user_content=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        await llm_usage_service.record_usage(
            db,
            room=room,
            agent_name=agent_name,
            identity_id=identity_id,
            provider="gemini",
            model=settings.gemini_model,
            action=action,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            estimated_cost=result.estimated_cost,
        )
        parsed = parse_json_block(result.text)
        if parsed is None:
            logger.warning(
                "Comms agent %s returned unparseable output (completion_tokens=%s): %r",
                action, result.completion_tokens, result.text[:300],
            )
            raise ProviderError(f"Comms agent returned unparseable output for {action}")
        return parsed

    async def clarify_inbound(
        self, db: AsyncSession, text: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> InboundClarification:
        prompt = comms_prompts.CLARIFICATION_PROMPT.format(original_text=text)
        parsed = await self._call(
            db, prompt=prompt, action="clarification", identity_id=identity_id, room=room,
            agent_name=agent_name, max_output_tokens=600,
        )
        return InboundClarification(
            detected_language=parsed.get("detected_language", "Unknown"),
            detected_code=(parsed.get("detected_code") or "")[:2].lower() or "en",
            clarification=parsed.get("clarification", text),
        )

    async def analyze_tone(
        self,
        db: AsyncSession,
        text: str,
        *,
        detected_language: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> dict:
        prompt = comms_prompts.TONE_ANALYSIS_PROMPT.format(detected_language=detected_language, original_text=text)
        return await self._call(
            db, prompt=prompt, action="tone_analysis", identity_id=identity_id, room=room,
            agent_name=agent_name, max_output_tokens=400,
        )

    async def translate_outbound(
        self,
        db: AsyncSession,
        text: str,
        *,
        chat_history: str,
        target_language: str,
        tone: str,
        character: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> OutboundTranslation:
        language = (target_language or "auto").strip().lower()
        if language in ("auto", ""):
            language_instruction = comms_prompts.TARGET_LANGUAGE_AUTO_INSTRUCTION
        else:
            language_instruction = comms_prompts.TARGET_LANGUAGE_EXPLICIT_INSTRUCTION.format(
                language=language.capitalize()
            )

        prompt = comms_prompts.OUTBOUND_TRANSLATION_PROMPT.format(
            character=character or "a helpful community assistant",
            chat_history=chat_history or "No previous conversation.",
            target_language_instruction=language_instruction,
            tone=tone or "friendly",
            client_text=text,
        )
        parsed = await self._call(
            db, prompt=prompt, action="outbound_translation", identity_id=identity_id, room=room,
            agent_name=agent_name, max_output_tokens=700,
        )
        translated = parsed.get("translated_text") or text
        key_points = parsed.get("key_points") or []
        if not isinstance(key_points, list):
            key_points = []
        return OutboundTranslation(
            translated_text=translated,
            key_points=[str(k) for k in key_points][:5],
            english_preview=parsed.get("english_preview") or translated,
        )

    async def generate_session_report(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        prompt = comms_prompts.SESSION_REPORT_PROMPT.format(transcript=transcript)
        return await self._call(
            db, prompt=prompt, action="session_report", identity_id=identity_id, room=room,
            agent_name=agent_name, max_output_tokens=800,
        )

    async def generate_satisfaction_analysis(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        prompt = comms_prompts.SATISFACTION_ANALYSIS_PROMPT.format(transcript=transcript)
        return await self._call(
            db, prompt=prompt, action="satisfaction_analysis", identity_id=identity_id, room=room,
            agent_name=agent_name, max_output_tokens=800,
        )
