"""UNIFIC's WhatsApp community service agent — the reply-drafting step
behind the Meeting Room's Auto mode. Open and conversational: it uses the
conversation's own history for continuity and may draw on
`context_snippets` (still restricted upstream to the room's own Shelf 1,
approved_for_auto_reply items — see
app.meeting_room.services._approved_context) as optional reference
material, but is no longer hard-limited to only ever repeating that
material. `FALLBACK_REPLY` is still used, just narrower now: only when the
provider call itself fails (see the `except ProviderError` path in
app.meeting_room.services._auto_reply), never as a "nothing approved
matched" short-circuit.

Extension points for future work (not implemented here):
  - Vector search / retrieval: a future step would enrich `context_snippets`
    with results from a vector-search lookup before this function builds
    its prompt — i.e. upstream of `generate_reply`, in
    app.meeting_room.services._approved_context or a new sibling function.
  - Gemini function/tool calling: a future change would build a
    `types.Tool`/`FunctionDeclaration` list and pass it through to
    `gemini_client.generate()` (which does not currently accept a `tools`
    argument — that's the other half of this future change).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.common import RoomName
from app.core.providers.base import ReplyGenerator
from app.core.providers.gemini_client import GeminiResult, generate
from app.core.providers.stub_reply_generator import FALLBACK_REPLY
from app.core.services import llm_usage_service

SYSTEM_TEMPLATE = """You are UNIFIC's community service agent, chatting with a member of a rural community programme over WhatsApp.

## Who you are right now
- Role: {role}
- Tone: {tone}
- Complexity: {complexity} (match the member's likely reading level — keep sentences short and plain unless "advanced" is specified)
- Character/persona: {character}

## Conversation so far
{chat_history}

## Reference information
The organisation has provided the following approved information. Use it when it's relevant to the member's message, but you are not limited to only this — hold a natural, helpful conversation and use your own general knowledge for anything else a community member might reasonably ask.

{context}

## Rules
1. Never invent specific dates, amounts, names, or promises on the organisation's behalf that aren't in the reference information above.
2. Keep the reply short — this is a WhatsApp message, not an email. 1-3 sentences unless the topic genuinely needs more.
3. Write only the reply text itself. No preamble, no "Here is the reply:", no quotation marks around it.
4. Reply in English — a separate translation step handles the member's language.
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
        chat_history: str = "",
    ) -> str:
        context_block = "\n".join(f"- {s}" for s in context_snippets) if context_snippets else "(none provided)"
        system_instruction = SYSTEM_TEMPLATE.format(
            role=config.get("role", "member"),
            tone=config.get("tone", "friendly"),
            complexity=config.get("complexity", "standard"),
            character=config.get("character", "assistant"),
            chat_history=chat_history or "No previous conversation.",
            context=context_block,
        )

        result: GeminiResult = await generate(
            system_instruction=system_instruction,
            user_content=message_text,
            temperature=0.3,
            max_output_tokens=300,
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
