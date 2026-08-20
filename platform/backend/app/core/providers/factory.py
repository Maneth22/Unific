"""`TranslationProvider` selection — kept here, unchanged, as the one
provider switch NOT part of the Tools Registry (see
`app.core.services.tools_service`'s module docstring / the Tools Registry
design notes: `TranslationProvider` has no callers anywhere in the app
today; it predates this feature and is deliberately left as-is rather than
inventing a new call site for it).

Every other provider switch this module used to hold —
`get_whatsapp_provider`, `get_reply_generator`, `get_comms_agent`,
`get_video_provider` — has moved to `app.core.services.tools_service`
(`get_global_tool`/`get_tool_for_identity`), which resolves the concrete
implementation from the admin-editable Tools Registry (DB-backed,
runtime-switchable) instead of a `settings.*_provider` env string fixed at
process boot. See `docs/ARCHITECTURE.md`'s Tools Registry section.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.core.providers.base import TranslationProvider
from app.core.providers.mock_translation import MockTranslationProvider


@lru_cache
def get_translation_provider() -> TranslationProvider:
    if settings.translation_provider == "gemini":
        from app.core.providers.gemini_translation_provider import GeminiTranslationProvider

        return GeminiTranslationProvider()
    return MockTranslationProvider()
