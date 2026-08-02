"""Selects the configured provider implementation. This is the one place
that reads `settings.*_provider` — services depend on the ABCs from
`base.py`, never on a concrete provider class directly.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)
from app.core.providers.base import ReplyGenerator, TranslationProvider, VideoProvider, WhatsAppProvider
from app.core.providers.mock_translation import MockTranslationProvider
from app.core.providers.mock_video_provider import MockVideoProvider
from app.core.providers.mock_whatsapp import MockWhatsAppProvider
from app.core.providers.stub_reply_generator import StubReplyGenerator


@lru_cache
def get_whatsapp_provider() -> WhatsAppProvider:
    if settings.whatsapp_provider == "cloud_api":
        from app.core.providers.cloud_api_whatsapp import CloudAPIWhatsAppProvider

        return CloudAPIWhatsAppProvider()
    return MockWhatsAppProvider()


@lru_cache
def get_translation_provider() -> TranslationProvider:
    if settings.translation_provider == "gemini":
        from app.core.providers.gemini_translation_provider import GeminiTranslationProvider

        return GeminiTranslationProvider()
    return MockTranslationProvider()


@lru_cache
def get_reply_generator() -> ReplyGenerator:
    if settings.reply_provider == "gemini":
        from app.core.providers.gemini_reply_generator import GeminiReplyGenerator

        return GeminiReplyGenerator()
    return StubReplyGenerator()


@lru_cache
def get_comms_agent():
    from app.core.providers.base import CommsAgent  # noqa: F401 — return type

    if settings.comms_agent_provider == "gemini":
        from app.core.providers.gemini_comms_agent import GeminiCommsAgent

        return GeminiCommsAgent()
    from app.core.providers.mock_comms_agent import MockCommsAgent

    return MockCommsAgent()


@lru_cache
def get_video_provider() -> VideoProvider:
    if settings.video_provider != "livekit":
        if settings.livekit_url or settings.livekit_api_key or settings.livekit_api_secret:
            logger.warning(
                "LIVEKIT_URL/API_KEY/API_SECRET are set but VIDEO_PROVIDER=%r (not "
                "'livekit') — falling back to MockVideoProvider, which mints fake "
                "tokens. This is almost always an unset or misspelled VIDEO_PROVIDER "
                "env var; set VIDEO_PROVIDER=livekit to use the configured credentials.",
                settings.video_provider,
            )
        if settings.is_production:
            logger.error(
                "Running in production with VIDEO_PROVIDER=%r — every meeting join "
                "will receive a fake MockVideoProvider token and no participant will "
                "get real audio, video, or chat. Set VIDEO_PROVIDER=livekit.",
                settings.video_provider,
            )

    if settings.video_provider == "livekit":
        from app.core.providers.livekit_video_provider import LiveKitVideoProvider

        return LiveKitVideoProvider()
    return MockVideoProvider()
