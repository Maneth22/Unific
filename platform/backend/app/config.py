"""Central settings, loaded once from environment / .env.

Every other module reads configuration through `settings`, imported from
here — nothing reaches into `os.environ` directly outside this file.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
