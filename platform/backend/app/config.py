"""Central settings, loaded once from environment / .env.

Every other module reads configuration through `settings`, imported from
here — nothing reaches into `os.environ` directly outside this file.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"

    # Database
    database_url: str = "postgresql+asyncpg://unific:unific_dev_password@localhost:55432/unific_platform"

    # JWT
    jwt_secret: str = "change-me-generate-a-real-64-byte-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14

    # Secrets envelope encryption (Fernet key, urlsafe-base64, 32 bytes)
    secrets_encryption_key: str = "change-me-generate-a-real-fernet-key"

    # CORS — comma-separated list of allowed origins
    cors_origins: str = "http://localhost:5173"

    # Login protection
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Providers
    whatsapp_provider: str = "mock"
    translation_provider: str = "mock"
    reply_provider: str = "stub"
    # The Meeting Room's intermediary agent (clarify/tone/translate/reports).
    comms_agent_provider: str = "gemini"

    whatsapp_cloud_api_token: str = ""
    whatsapp_cloud_api_phone_number_id: str = ""
    whatsapp_cloud_api_verify_token: str = ""
    # Graph API version segment (e.g. "v20.0") used to build every Cloud
    # API URL in cloud_api_whatsapp.py — was previously a hardcoded module
    # constant; kept configurable here since Meta deprecates old versions.
    whatsapp_api_version: str = "v20.0"
    # App-level credentials — only needed for the WhatsApp Diagnostics
    # panel's webhook-status check, which reads Meta's `/subscriptions`
    # edge (a per-app resource, not per-phone-number). Sending/receiving
    # messages works fine with the three fields above alone.
    whatsapp_cloud_api_app_id: str = ""
    whatsapp_cloud_api_app_secret: str = ""

    # The dialable agent number (digits, with country code, no "+") used
    # to build `wa.me` click-to-chat deep links after public member
    # registration. Distinct from whatsapp_cloud_api_phone_number_id
    # above, which is a Graph API resource id, not a dialable number.
    whatsapp_agent_display_number: str = ""
    whatsapp_invite_prefill_template: str = "Hi, I'm {name} from {group_name}. I just registered and would like to talk."

    # Canonical frontend origin, used server-side to build links returned
    # to a dashboard (e.g. a community's registration invite URL). Must
    # match the frontend's actual dev port (see frontend/vite.config.js
    # and CORS_ORIGINS above — both use 5183, not Vite's generic 5173
    # default) or generated invite links point at a port nothing is
    # listening on.
    frontend_base_url: str = "http://localhost:5183"

    # This backend's own public origin — used to compute the webhook URL
    # Meta *should* have on file, for the WhatsApp Diagnostics panel's
    # webhook-status check (see `whatsapp_cloud_api_app_id` above).
    backend_base_url: str = "http://localhost:8000"

    # Gemini — backs REPLY_PROVIDER=gemini / TRANSLATION_PROVIDER=gemini.
    # gemini-flash-lite is the same cheap-model choice the prototype made,
    # which matters given the docs' near-free base-service target.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_rate_limit_delay: float = 0.2
    gemini_max_concurrent: int = 4

    # Rough per-token cost estimates for the AI Usage dashboard, in USD
    # per 1,000 tokens. These are estimates, not billing data — correct
    # them against your actual Gemini invoice; the point is a usable
    # relative signal (who/what is using tokens) now, with real $ figures
    # to follow once actual billing is observed.
    gemini_input_cost_per_1k_tokens: float = 0.000075
    gemini_output_cost_per_1k_tokens: float = 0.0003

    # Video conferencing (LiveKit) — backs the Meeting Room's live calls.
    # video_provider defaults to "mock" like every other provider switch,
    # so a bare checkout runs with zero config; set VIDEO_PROVIDER=livekit
    # and fill in the three fields below (LiveKit's own standard env var
    # names — their SDKs read these by default) to use a real deployment.
    video_provider: str = "mock"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # How long a passwordless meeting-invite link stays valid past the
    # meeting's scheduled_at, and how long a LiveKit access token is valid
    # once minted for a participant.
    meeting_invite_ttl_hours: int = 6
    meeting_token_ttl_minutes: int = 180

    # Live captions / dubbed audio / translated chat (LiveKit Agents,
    # embedded in this process — see app/meeting_room/live_agents/). One bot
    # identity per meeting; STT/TTS are pluggable per language via the two
    # JSON maps below, Gemini is used only for translation (language-pair-
    # agnostic, no per-language config needed for it).
    live_agents_bot_identity: str = "unific-agent"
    live_agents_default_language: str = "en"
    # Master off-switch for captions + dubbed audio, independent of chat
    # translation (which only needs Gemini and is unaffected by this).
    # Defaults to False FOR NOW — no STT (Deepgram/Azure/Google) or TTS
    # (Azure) credentials are configured yet, and constructing those SDK
    # clients without them can synchronously block on network/auth (most
    # notably Google's client libraries reaching for the GCP metadata
    # server when no explicit credentials exist) — since this whole app
    # is one embedded asyncio process, a single blocking call like that
    # freezes EVERY request the server is handling, not just the caption
    # pipeline, until the process is restarted. Flip to True once
    # DEEPGRAM_API_KEY / AZURE_SPEECH_KEY+REGION / GOOGLE_APPLICATION_
    # CREDENTIALS are actually set up — see orchestrator.py, which is the
    # only place that reads this.
    live_agents_captions_enabled: bool = False
    # Deliberately separate from gemini_model above (that one backs the
    # WhatsApp reply/translation path) — lets the two be tuned/priced
    # independently even though they may point at the same model today.
    #
    # NOT "gemini-2.5-flash" — verified live against generate_content with
    # this project's actual GEMINI_API_KEY (2026-08-18) that model 404s:
    # "This model models/gemini-2.5-flash is no longer available to new
    # users. Please update your code to use models/gemini-3.6-flash" — the
    # exact "listed as available but 404s on generateContent for this key"
    # trap. gemini-3.6-flash was confirmed working (real translation
    # output) with a live call before being set here.
    live_agents_gemini_model: str = "gemini-3.6-flash"

    # Which of TranslatorManager's two prompt strategies in-call CHAT
    # translation (chat_relay.py only — captions.py is unaffected, it
    # always uses "generic_first") tries FIRST for a given message:
    #   "specialized_first" — the Singlish/Hinglish-aware, per-source-
    #       language multi-target JSON prompt (see translator.FALLBACK_
    #       PROMPTS) goes first; the generic single-pair prompt is the
    #       rescue attempt if that fails.
    #   "generic_first" — the original ordering: generic single-pair
    #       prompt first, specialized prompt only as the rescue attempt.
    # Set to "specialized_first" as the default FOR NOW, since it's the
    # one that correctly handles the romanized Sinhala/Hindi chat text
    # this platform's community actually sends day to day — flip back to
    # "generic_first" here (no code change needed) if that turns out
    # not to hold up.
    live_agents_chat_translation_mode: str = "specialized_first"

    # {language_code: stt_provider_name} — the single source of truth for
    # which languages are selectable at all (see live_agents.providers.
    # SELECTABLE_LANGUAGES). Sinhala ("si") is intentionally NOT mapped to
    # "deepgram" — verified against LiveKit's own docs that Deepgram's
    # supported-language set doesn't include it; Google Cloud Speech
    # (Chirp 3) does.
    live_agents_stt_provider_map: str = '{"en": "deepgram", "hi": "deepgram", "si": "google"}'
    # {language_code: {"provider": ..., "voice": ...}} — a language present
    # in the STT map but absent here still fully supports captions_only;
    # it just can't be selected for audio_mode=dubbed_audio (see
    # live_agents.providers.get_tts_for_language, which returns None rather
    # than raising for that case).
    live_agents_tts_provider_map: str = (
        '{"hi": {"provider": "azure", "voice": "hi-IN-SwaraNeural"},'
        ' "si": {"provider": "azure", "voice": "si-LK-SameeraNeural"}}'
    )

    # Deepgram (STT: en, hi via the map above).
    deepgram_api_key: str = ""
    # Azure Speech (STT fallback for si; TTS for hi/si) — same two
    # credentials back both the STT and TTS Azure plugins.
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    # Google Cloud Speech (STT: si, via Chirp 3) reads GOOGLE_APPLICATION_
    # CREDENTIALS directly from the environment (a GCP service-account JSON
    # file path) — NOT the same credential as gemini_api_key above. Gemini's
    # Developer API key and a GCP service account are two unrelated
    # products/billing relationships; don't conflate them when provisioning.

    # Three independent concurrency caps replacing the old single
    # live_translation_max_concurrent_sessions semaphore, since the cost
    # unit is no longer "one persistent Gemini Live session per
    # (speaker, language)" — it's now three separable things: one STT
    # session per speaker, one TTS/queue-writer pipeline per active target
    # language actually in dubbed-audio demand, and stateless Gemini
    # translate calls per distinct target language per segment/message.
    # All three tuned for a 1vCPU/2GB droplet — adjust per host.
    live_agents_max_concurrent_stt_sessions: int = 8
    live_agents_max_concurrent_tts_pipelines: int = 6
    live_agents_max_concurrent_translate_calls: int = 8
    # Per-language dubbed-audio backlog depth — a segment arriving once this
    # is full is dropped (the newest arrival, not the oldest queued one; see
    # live_agents.dubbed_audio.LanguageAudioPipeline) rather than left to
    # grow into ever-more-stale queued audio.
    live_agents_dub_queue_maxsize: int = 4

    # WhatsApp community agent session cache (app/agents/whatsapp_community).
    # Redis holds same-day conversation turns + per-day counters; Postgres
    # only gets written at end-of-day flush (or via the admin flush route).
    # The 1500-token cap and the daily-reply-cap counter both reset at the
    # same UTC-midnight boundary as the EOD flush cron below — one time
    # semantic instead of three independent rolling windows.
    redis_url: str = "redis://localhost:6379/0"
    whatsapp_session_token_cap: int = 1500
    eod_flush_hour_utc: int = 0
    eod_flush_minute_utc: int = 10

    # General API rate limiting (slowapi, Redis-backed — see app/core/rate_limit.py).
    # The webhook gets its own stricter limit since it's the one unauthenticated
    # route in the app; rate_limit_enabled is turned off in tests via conftest.
    rate_limit_enabled: bool = True
    rate_limit_default: str = "60/minute"
    rate_limit_webhook: str = "120/minute"
    # The meeting-wide open/shareable invite link (see
    # meeting_room.models.MeetingInviteKind.open) is a stable,
    # publicly-postable URL (e.g. dropped into a WhatsApp group) that
    # mints a new guest participant + LiveKit connection on every
    # redemption — worth its own tighter cap than rate_limit_default,
    # mirroring rate_limit_webhook's own dedicated limit for the same
    # "unauthenticated, externally-reachable" reasoning.
    rate_limit_open_join: str = "20/minute"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def live_agents_stt_provider_map_dict(self) -> dict[str, str]:
        return json.loads(self.live_agents_stt_provider_map)

    @property
    def live_agents_tts_provider_map_dict(self) -> dict[str, dict]:
        return json.loads(self.live_agents_tts_provider_map)

    @model_validator(mode="after")
    def _validate_live_agents_provider_maps(self) -> "Settings":
        # Fail fast at process boot on a malformed .env value, rather than
        # on the first live meeting that tries to use it.
        json.loads(self.live_agents_stt_provider_map)
        json.loads(self.live_agents_tts_provider_map)
        valid_modes = {"specialized_first", "generic_first"}
        if self.live_agents_chat_translation_mode not in valid_modes:
            raise ValueError(
                f"live_agents_chat_translation_mode must be one of {sorted(valid_modes)}, "
                f"got {self.live_agents_chat_translation_mode!r}"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
