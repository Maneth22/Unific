"""Real reply drafting for the Meeting Room's Auto mode. Hard-constrained
by prompt to the `context_snippets` it's given — which the pipeline
(app.meeting_room.services._approved_context) already restricts to the
room's own Shelf 1, approved_for_auto_reply items. This file must never
be handed anything beyond those snippets; it has no other source of
truth and is instructed to say so rather than guess.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.common import RoomName
from app.core.providers.base import ReplyGenerator
from app.core.providers.gemini_client import GeminiResult, generate
from app.core.providers.stub_reply_generator import FALLBACK_REPLY
from app.core.services import llm_usage_service

SYSTEM_TEMPLATE = """You are a community assistant replying on behalf of an organisation, over WhatsApp, to a member of a rural community programme.

## Who you are right now
- Role: {role}
- Tone: {tone}
- Complexity: {complexity} (match the member's likely reading level — keep sentences short and plain unless "advanced" is specified)
- Character/persona: {character}

## The only information you may use
You may ONLY answer using the approved information below. You have no other knowledge of this organisation, its programmes, schedules, or policies — anything not in this list is unknown to you.

Approved information:
{context}

## Hard rules
1. If the approved information above does not answer the member's question, do not guess, infer, or use general knowledge. Instead reply with exactly: "{fallback}"
2. Never invent dates, amounts, names, or promises that are not explicitly in the approved information.
3. Keep the reply short — this is a WhatsApp message, not an email. 1-3 sentences unless the approved information genuinely requires more.
4. Write only the reply text itself. No preamble, no "Here is the reply:", no quotation marks around it.
5. Reply in English — a separate translation step handles the member's language.
"""


class GeminiReplyGenerator(ReplyGenerator):
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
            # No approved material to draw from — don't spend a call
            # guessing; this is exactly the doc's "must not reach beyond
            # Comms" boundary in practice.
            return FALLBACK_REPLY

        context_block = "\n".join(f"- {s}" for s in context_snippets)
        system_instruction = SYSTEM_TEMPLATE.format(
            role=config.get("role", "member"),
            tone=config.get("tone", "friendly"),
            complexity=config.get("complexity", "standard"),
            character=config.get("character", "assistant"),
            context=context_block,
            fallback=FALLBACK_REPLY,
        )

        result: GeminiResult = await generate(
            system_instruction=system_instruction,
            user_content=message_text,
            temperature=0.3,
            max_output_tokens=200,
        )

        await llm_usage_service.record_usage(
            db,
            room=room,
            agent_name=agent_name,
            identity_id=identity_id,
            provider="gemini",
            model=settings.gemini_model,
            action="reply_generation",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            estimated_cost=result.estimated_cost,
        )

        return result.text or FALLBACK_REPLY
