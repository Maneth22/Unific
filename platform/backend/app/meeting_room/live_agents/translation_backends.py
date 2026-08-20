"""The live-meeting translation engine as a pluggable backend — the Tools
Registry's `meeting_translation` slot. Lives here, not
`app.core.providers.base`, since it's meeting-room-specific (the shared
`core` ABCs are for things Resources/Assets will also need — see that
module's own docstring); `core` must never import from a room package, so
this slot's small factory registry lives alongside its ABC instead of in
`app.core.services.tools_registry` (which only tracks this slot's valid
`tool_key`s for catalog/validation purposes, see that module's docstring).

`TranslatorManager` (`translator.py`) only ever calls `generate()` — the
two internal prompt strategies (`_attempt_generic`/`_attempt_specialized`,
the Singlish/Hinglish detection) are unaffected by which backend answers
them; only "which LLM service does the actual completion" is what this
abstraction swaps.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class LiveTranslationBackend(ABC):
    @abstractmethod
    async def generate(self, *, text: str, system_instruction: str, json_mode: bool) -> str | None:
        """Returns the raw text/JSON response, or `None` on any failure
        (timeout, rate limit, malformed/empty response) — never raises.
        `translator.py`'s `_attempt_generic`/`_attempt_specialized` already
        implement "return None to signal try-the-other-strategy" inline
        for the one backend that existed before this abstraction; every
        backend must keep that same contract."""


def get_backend(tool_key: str) -> LiveTranslationBackend:
    factory = _FACTORIES.get(tool_key)
    if factory is None:
        raise ValueError(f"No live-translation backend registered for tool_key={tool_key!r}")
    return factory()


def _build_gemini() -> LiveTranslationBackend:
    from app.meeting_room.live_agents.gemini_translation_backend import GeminiLiveTranslationBackend

    return GeminiLiveTranslationBackend()


# Gemini is the only live-translation backend (the OpenAI backend was
# removed — Google-only is a deliberate product decision, not a temporary
# state). Keep in sync with
# app.core.services.tools_registry._MEETING_TRANSLATION_KEYS.
_FACTORIES: dict[str, Callable[[], LiveTranslationBackend]] = {
    "gemini": _build_gemini,
}
