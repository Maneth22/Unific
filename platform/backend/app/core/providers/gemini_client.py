"""Thin, rate-limited wrapper around the Gemini SDK, shared by the reply
generator and translation provider. The SDK call is synchronous, so it
runs in a thread executor; a semaphore + small delay cap concurrency —
the same pattern the prototype (E:\\Unific-Solutions) used, since it's
already proven against real Gemini rate limits.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from decimal import Decimal

from app.config import settings
from app.core.providers.base import ProviderError


def parse_json_block(text: str) -> dict | None:
    """Parses a model response expected to be a raw JSON object, tolerating
    the ```json fences Gemini sometimes adds anyway. Returns None (never
    raises) on anything unparseable — callers decide their own fallback.
    Same tolerance logic the prototype used."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    if cleaned.endswith("```"):
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.gemini_max_concurrent)
    return _semaphore


@contextlib.asynccontextmanager
async def _rate_limited():
    await asyncio.sleep(settings.gemini_rate_limit_delay)
    async with _get_semaphore():
        yield


class GeminiResult:
    def __init__(
        self,
        text: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
    ):
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens

    @property
    def estimated_cost(self) -> Decimal | None:
        """Rough $ estimate from `settings.gemini_*_cost_per_1k_tokens` —
        see that setting's docstring: correct against real billing."""
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        input_cost = Decimal(str(self.prompt_tokens or 0)) / 1000 * Decimal(str(settings.gemini_input_cost_per_1k_tokens))
        output_cost = Decimal(str(self.completion_tokens or 0)) / 1000 * Decimal(str(settings.gemini_output_cost_per_1k_tokens))
        return input_cost + output_cost


# Transient Gemini-side conditions worth retrying: capacity spikes (503),
# rate limits (429). Observed regularly on the free tier — a couple of
# short backoff retries absorbs most of them.
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")
_RETRY_DELAYS = (1.5, 3.0)


async def generate(
    *, system_instruction: str, user_content: str, temperature: float = 0.3, max_output_tokens: int = 400
) -> GeminiResult:
    """Runs one Gemini generate_content call, retrying transient 503/429
    errors with backoff. Raises ProviderError on any final failure —
    never lets a raw SDK exception escape into the pipeline."""
    if not settings.gemini_api_key:
        raise ProviderError("Gemini is not configured — set GEMINI_API_KEY, or use a mock/stub provider for development.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ProviderError("google-genai package is not installed") from exc

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    response = None
    last_exc: Exception | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            async with _rate_limited():
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=settings.gemini_model, contents=user_content, config=config
                    ),
                )
            break
        except Exception as exc:
            last_exc = exc
            transient = any(marker in str(exc) for marker in _TRANSIENT_MARKERS)
            if transient and attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            raise ProviderError(f"Gemini call failed: {exc}") from exc
    if response is None:
        raise ProviderError(f"Gemini call failed: {last_exc}")

    text = (response.text or "").strip()
    prompt_tokens = completion_tokens = total_tokens = None
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_token_count", None)
        completion_tokens = getattr(usage, "candidates_token_count", None)
        total_tokens = getattr(usage, "total_token_count", None)

    return GeminiResult(
        text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens
    )
