"""Config-driven STT/TTS provider registry — the "kitchen" behind the
Tools Registry's `meeting_stt`/`meeting_tts` slots (see
`app.core.services.tools_registry`'s module docstring: `core` never
imports this module directly, only tracks which `tool_key`s are valid for
these two slots; actual construction always happens here).

STT: `is_stt_language_supported`/`get_shared_speech_client`/
`google_stt_recognizer_path` back captions.py's DIRECT Google
Speech-to-Text v2 streaming integration (see that module's own docstring
for why it doesn't go through livekit-agents/AgentSession at all). TTS:
`get_tts_for_language` still takes an optional resolved `{language:
tool_key}` map (a meeting's/identity's effective Tools Registry choice,
see `tools_service.EffectiveToolConfig`) and falls back to
`settings.live_agents_tts_provider_map` (JSON dict, see `app.config`)
when none is given — nothing here is a hardcoded per-language `if`/`elif`
chain, so adding a 4th language is a config/selection change, not a code
change.

Google is the only STT/TTS provider wired up (Deepgram/Azure/OpenAI/
ElevenLabs were removed — Google-only is a deliberate product decision,
not a temporary state); the STT half is bound to Google specifically by
design now (direct API integration, not a swappable factory) — only TTS
still has a per-provider `TTS_FACTORIES` registry.

Gemini (used only for translation, see `translator.py` and
`translation_backends.py`) is deliberately absent from this file: the
live-translation engine is language-pair-agnostic and needs no
per-language configuration at all.

Every `livekit.plugins.*`/`google.cloud.*` import in this file is done
lazily, inside the function that actually needs it, not at module import
time — same lazy-import convention `app.core.services.tools_registry`
uses for its own four provider switches, so a deployment that never
touches live captions/dubbing in a given run (e.g. most test runs, which
exercise `translate_live=False` paths only) never pays the cost of
loading these SDKs at all.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from google.auth.credentials import Credentials
    from google.cloud.speech_v2 import SpeechAsyncClient
    from livekit.agents import tts as tts_types


class UnsupportedLanguageError(Exception):
    """Raised when a language has no STT provider configured for it at
    all — the caller (captions.py) treats this as "can't caption this
    speaker," not a crash."""


# Chirp 3 (Google Cloud Speech) wants a region-qualified BCP-47 code (e.g.
# "si-LK"), not the bare ISO 639-1 code this app otherwise uses everywhere
# else (participant attributes, the STT/TTS provider maps,
# MeetingChatMessage.source_language, ...). This is the one place that
# distinction matters — extend it alongside the provider maps when a new
# language is added.
_REGION_CODE_BY_LANGUAGE = {
    "en": "en-US",
    "hi": "hi-IN",
    "si": "si-LK",
}


def _region_code(lang: str) -> str:
    return _REGION_CODE_BY_LANGUAGE.get(lang, lang)


def is_stt_language_supported(lang: str, stt_map: dict[str, str] | None = None) -> bool:
    """Direct, config-driven check — replaces the old get_stt_for_language's
    "construct a livekit.plugins.google.STT and hand it back" contract.
    captions.py talks to Google's Speech-to-Text v2 streaming API
    directly (no livekit-agents AgentSession/RoomIO/VAD — that pulled in
    onnxruntime, which crashes with an illegal CPU instruction on any
    pre-AVX2 CPU and isn't needed here: this session only ever consumes
    raw mic audio and emits final transcripts, no LLM/TTS turn to
    manage). This function keeps the SAME config surface (`stt_map`/
    `settings.live_agents_stt_provider_map_dict`, still gated through the
    Tools Registry's `meeting_stt` slot) without constructing anything."""
    source = stt_map if stt_map is not None else settings.live_agents_stt_provider_map_dict
    return source.get(lang) == "google"


def _google_credentials_kwargs() -> dict:
    """`settings.google_application_credentials` is passed explicitly as
    `credentials_file` rather than relied on via the ambient
    GOOGLE_APPLICATION_CREDENTIALS/ADC env var — this app never exports
    it to the real OS environment just because it's in `.env` (see that
    setting's own comment; confirmed directly: every Google client
    constructed without this used to silently fail auth). Empty string
    (the default) falls through to plain ADC, unchanged, for a
    deployment that has real ambient credentials (e.g. GCP hosting)."""
    if settings.google_application_credentials:
        return {"credentials_file": settings.google_application_credentials}
    return {}


_google_credentials: "Credentials | None" = None
_google_project_id: str | None = None
_shared_speech_clients: dict[str, "SpeechAsyncClient"] = {}

# Chirp 3 does NOT support every language STT_PROVIDER_MAP lists — Sinhala
# specifically isn't available on Chirp 3 in any GA location. Confirmed
# directly against the live API: a chirp_3/"us" request for "si-LK" 400s
# with "The language si-LK is not supported by the model chirp_3 in the
# location named us"; chirp_2/"asia-southeast1" accepts it (both batch and
# streaming recognize verified live). This is a per-language MODEL +
# LOCATION override, not just a region-code spelling difference (that's
# _REGION_CODE_BY_LANGUAGE above) — every language not listed here uses
# the default (chirp_3, settings.live_agents_google_stt_location).
_STT_MODEL_LOCATION_OVERRIDES: dict[str, tuple[str, str]] = {
    "si": ("chirp_2", "asia-southeast1"),
}
_DEFAULT_STT_MODEL = "chirp_3"


def stt_model_and_location(lang: str) -> tuple[str, str]:
    """(model, location) to use for this language's STT — see
    _STT_MODEL_LOCATION_OVERRIDES above for why this isn't a single global
    pair. captions.py uses both halves: `model` in its RecognitionConfig,
    `location` (via get_shared_speech_client/google_stt_recognizer_path
    below) to pick the right regional client + recognizer path."""
    if lang in _STT_MODEL_LOCATION_OVERRIDES:
        return _STT_MODEL_LOCATION_OVERRIDES[lang]
    return _DEFAULT_STT_MODEL, settings.live_agents_google_stt_location


def _load_google_credentials() -> "Credentials | None":
    """Loads once and caches — `None` when no key file is configured,
    which falls through to plain ADC (ambient env var / GCP metadata
    server), unchanged behavior for a deployment that has that set up."""
    global _google_credentials, _google_project_id
    if _google_credentials is not None or not settings.google_application_credentials:
        return _google_credentials
    from google.oauth2 import service_account

    _google_credentials = service_account.Credentials.from_service_account_file(
        settings.google_application_credentials
    )
    _google_project_id = _google_credentials.project_id
    return _google_credentials


def google_stt_recognizer_path(location: str) -> str:
    """The one recognizer resource every streaming/batch v2 call in this
    app targets for a given location — the implicit, always-available
    default recognizer for the whole project (see
    settings.live_agents_google_stt_location's own comment on why this
    can't be "global" for Chirp 3, and stt_model_and_location above for
    why `location` is per-language, not a single fixed value)."""
    _load_google_credentials()
    if _google_project_id is None:
        raise UnsupportedLanguageError(
            "GOOGLE_APPLICATION_CREDENTIALS is not configured — cannot resolve a Google Cloud project id"
        )
    return f"projects/{_google_project_id}/locations/{location}/recognizers/_"


def get_shared_speech_client(location: str) -> "SpeechAsyncClient":
    """One SpeechAsyncClient per location, reused across every speaker/
    meeting that needs that location — constructing one per speaker would
    mean a fresh gRPC channel + auth handshake per person who talks, real
    unnecessary overhead this cache avoids. Keyed by location (not a
    single shared instance) since Sinhala's chirp_2/asia-southeast1
    override needs a different regional endpoint than everything else's
    chirp_3/us default — see stt_model_and_location above."""
    if location not in _shared_speech_clients:
        from google.api_core.client_options import ClientOptions
        from google.cloud.speech_v2 import SpeechAsyncClient

        # Same "global" caveat as the old livekit-plugin path: Chirp 3
        # doesn't exist under the default global endpoint, only under a
        # region-qualified one.
        client_options = ClientOptions(api_endpoint=f"{location}-speech.googleapis.com") if location != "global" else None
        _shared_speech_clients[location] = SpeechAsyncClient(
            client_options=client_options, credentials=_load_google_credentials()
        )
    return _shared_speech_clients[location]


def stt_region_code(lang: str) -> str:
    """Public wrapper — captions.py needs this to build its
    RecognitionConfig's language_codes; TTS below uses the private
    `_region_code` directly since it's in the same module."""
    return _region_code(lang)


def _google_tts(lang: str, voice: str) -> "tts_types.TTS":
    from livekit.plugins import google

    return google.TTS(voice_name=voice, language=_region_code(lang), **_google_credentials_kwargs())


TTS_FACTORIES = {
    "google": _google_tts,
}


def get_tts_for_language(lang: str, tts_map: dict[str, dict] | None = None) -> "tts_types.TTS | None":
    """`None` (not an exception) when the language has no TTS entry — the
    caller (dubbed_audio.py) degrades `audio_mode=dubbed_audio` to
    `captions_only` for that language and logs it; this function never
    silently fails, it just reports "no dubbed audio here" as data.
    `tts_map` follows the same resolved-map-or-settings-fallback contract
    as `get_stt_for_language` above — each entry is `{"provider": ...,
    "voice": ...}`, same shape `settings.live_agents_tts_provider_map_dict`
    already used."""
    source = tts_map if tts_map is not None else settings.live_agents_tts_provider_map_dict
    entry = source.get(lang)
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
