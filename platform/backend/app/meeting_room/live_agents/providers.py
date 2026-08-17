"""Config-driven STT/TTS provider registry.

Every language this app can transcribe/synthesize is declared in
`settings.live_agents_stt_provider_map` / `live_agents_tts_provider_map`
(JSON dicts, see `app.config`) — nothing here is a hardcoded per-language
`if`/`elif` chain, so adding a 4th language later is a config change, not
a code change (only a new *provider* — as opposed to a new language on an
already-supported provider — would need a new factory function here).

Gemini (used only for translation, see `translator.py`) is deliberately
absent from this file: it's language-pair-agnostic and needs no
per-language configuration at all.

Every `livekit.agents`/`livekit.plugins.*` import in this file is done
lazily, inside the function that actually needs it, not at module import
time — same convention `app.core.providers.factory` already uses for its
own provider switches. This isn't just style here: `livekit-agents` pulls
in onnxruntime/azure-cognitiveservices-speech/google-cloud-speech, real
weight to load into every process at boot even on a deployment that never
touches live captions in a given run (e.g. most test runs, which exercise
`translate_live=False` paths only) — deferring the import means paying
that cost only when a meeting actually needs it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from livekit.agents import stt as stt_types
    from livekit.agents import tts as tts_types
    from livekit.agents.vad import VAD


class UnsupportedLanguageError(Exception):
    """Raised when a language has no STT provider configured for it at
    all — the caller (captions.py) treats this as "can't caption this
    speaker," not a crash."""


def _deepgram_stt(lang: str) -> "stt_types.STT":
    from livekit.plugins import deepgram

    return deepgram.STT(model="nova-3", language=lang, api_key=settings.deepgram_api_key)


# Chirp 3 (Google Cloud Speech) and Azure Speech both want a region-
# qualified BCP-47 code (e.g. "si-LK"), not the bare ISO 639-1 code this
# app otherwise uses everywhere else (participant attributes, the STT/TTS
# provider maps, MeetingChatMessage.source_language, ...). This is the one
# place that distinction matters — extend it alongside the provider maps
# when a new language is added.
_REGION_CODE_BY_LANGUAGE = {
    "hi": "hi-IN",
    "si": "si-LK",
}


def _region_code(lang: str) -> str:
    return _REGION_CODE_BY_LANGUAGE.get(lang, lang)


def _google_stt(lang: str) -> "stt_types.STT":
    from livekit.plugins import google

    return google.STT(languages=_region_code(lang), model="chirp_3", location="global")


def _azure_stt(lang: str) -> "stt_types.STT":
    from livekit.plugins import azure

    return azure.STT(
        speech_key=settings.azure_speech_key,
        speech_region=settings.azure_speech_region,
        language=_region_code(lang),
    )


STT_FACTORIES = {
    "deepgram": _deepgram_stt,
    "google": _google_stt,
    "azure": _azure_stt,
}


def _azure_tts(lang: str, voice: str) -> "tts_types.TTS":
    from livekit.plugins import azure

    return azure.TTS(voice=voice, speech_key=settings.azure_speech_key, speech_region=settings.azure_speech_region)


TTS_FACTORIES = {
    "azure": _azure_tts,
}

_shared_vad: "VAD | None" = None


def get_shared_vad() -> "VAD":
    """One Silero VAD instance for the whole process, loaded once and
    cached — loading it is real CPU/RAM cost (an ONNX model), it must
    never repeat per speaker. `force_cpu=True` is Silero's own default,
    matches this being a 1vCPU/2GB droplet with no GPU."""
    global _shared_vad
    if _shared_vad is None:
        from livekit.plugins import silero

        _shared_vad = silero.VAD.load()
    return _shared_vad


def get_stt_for_language(lang: str) -> "stt_types.STT":
    provider_name = settings.live_agents_stt_provider_map_dict.get(lang)
    if provider_name is None:
        raise UnsupportedLanguageError(f"No STT provider configured for language {lang!r}")
    factory = STT_FACTORIES.get(provider_name)
    if factory is None:
        raise UnsupportedLanguageError(f"Unknown STT provider {provider_name!r} for language {lang!r}")
    return factory(lang)


def get_tts_for_language(lang: str) -> "tts_types.TTS | None":
    """`None` (not an exception) when the language has no TTS entry — the
    caller (dubbed_audio.py) degrades `audio_mode=dubbed_audio` to
    `captions_only` for that language and logs it; this function never
    silently fails, it just reports "no dubbed audio here" as data."""
    entry = settings.live_agents_tts_provider_map_dict.get(lang)
    if entry is None:
        return None
    factory = TTS_FACTORIES.get(entry["provider"])
    if factory is None:
        raise UnsupportedLanguageError(f"Unknown TTS provider {entry['provider']!r} for language {lang!r}")
    return factory(lang, entry["voice"])


def selectable_languages() -> list[str]:
    """Always-current list of languages a participant can select at all —
    anything with an STT entry. TTS coverage (`get_tts_for_language`) is a
    strict subset that only gates `audio_mode=dubbed_audio` availability,
    never captions. Re-reads `settings` on every call (unlike the frozen
    `SELECTABLE_LANGUAGES` module constant below) so tests can monkeypatch
    `settings.live_agents_stt_provider_map` and see it reflected."""
    return list(settings.live_agents_stt_provider_map_dict.keys())


# Frozen at import time, same convention the old live_translation.py's
# plain hardcoded SELECTABLE_LANGUAGES list followed (env-configured
# provider maps don't change at runtime in this app, same as every other
# Settings field) — the single source of truth router.py/schemas.py import
# for "which languages exist at all". Use selectable_languages() instead
# wherever a live/testable read is actually needed.
SELECTABLE_LANGUAGES: list[str] = selectable_languages()
