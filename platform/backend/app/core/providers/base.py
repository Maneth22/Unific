"""Provider interfaces for external connectors — WhatsApp, translation,
reply generation, and video conferencing. Defined here in `core`, not
`meeting_room`, because
Tasks 6-7 (Resources, Assets) will need identically-shaped external
connectors later; this is the "define the room contract once" piece the
Flags & Issues doc calls for.

Every provider is selected via env (see `app.config`) and defaults to a
mock/stub implementation — no live WhatsApp or LLM credentials are
required to run the full message pipeline in development.

`TranslationProvider` and `ReplyGenerator` take `db`/`identity_id`/`room`/
`agent_name` so a real (LLM-backed) implementation can record its own
usage via `core.llm_usage_service` — see `gemini_reply_generator.py` /
`gemini_translation_provider.py`. Mock/stub implementations ignore these
and never record usage, so usage stats only ever reflect real LLM spend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName


@dataclass
class InboundWhatsAppMessage:
    from_phone: str
    text: str
    provider_message_id: str


class ProviderError(Exception):
    """Raised for a provider-side failure (rate limit, timeout, not
    configured) — callers must handle this without ever crashing the
    message pipeline; a failed send should be logged, not fatal."""


class WhatsAppProvider(ABC):
    @abstractmethod
    async def send_message(self, to_phone: str, text: str) -> str:
        """Returns a provider-assigned message id."""

    @abstractmethod
    def parse_webhook(self, payload: dict) -> list[InboundWhatsAppMessage]:
        """Parses a raw inbound webhook payload into normalized messages."""


class TranslationProvider(ABC):
    @abstractmethod
    async def detect_language(
        self, db: AsyncSession, text: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> str:
        """Returns an ISO-639-1-ish language code."""

    @abstractmethod
    async def translate(
        self,
        db: AsyncSession,
        text: str,
        *,
        source_lang: str | None,
        target_lang: str,
        tone: str | None = None,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> str:
        """`tone` is carried through so character/tone survives
        translation, per the docs: "kept the same when a message is
        translated." Optional — a provider that can't act on it may
        ignore it."""


class ReplyGenerator(ABC):
    @abstractmethod
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
        """`context_snippets` is drawn only from the Meeting Room's own
        Shelf 1 (Operational Library, approved_for_auto_reply=True) —
        callers must never pass it anything else."""


@dataclass
class InboundClarification:
    """What the comms agent makes of a raw community message: the detected
    language and a clear-English restatement the client can read."""

    detected_language: str  # full name, e.g. "Hindi"
    detected_code: str      # ISO 639-1, e.g. "hi"
    clarification: str      # clear English restatement


@dataclass
class OutboundTranslation:
    """A client message rendered for the community member: the translation
    in their language/tone/character voice, plus topic tags and an English
    preview of exactly what the translation says."""

    translated_text: str
    key_points: list[str]
    english_preview: str


class CommsAgent(ABC):
    """The Meeting Room's intermediary agent — the port of the prototype's
    clarification / tone-analysis / translation / session-report agents
    (see `comms_prompts.py`). One agent, five actions, so the whole
    bidirectional WhatsApp flow and its analysis share a single provider
    swap point. Every method takes `db`/`identity_id` so a real (LLM)
    implementation can record its usage per identity."""

    @abstractmethod
    async def clarify_inbound(
        self, db: AsyncSession, text: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> InboundClarification:
        """Community message -> detected language + clear English for the client."""

    @abstractmethod
    async def analyze_tone(
        self,
        db: AsyncSession,
        text: str,
        *,
        detected_language: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> dict:
        """Community message -> tone/proficiency/style insight JSON for the client."""

    @abstractmethod
    async def translate_outbound(
        self,
        db: AsyncSession,
        text: str,
        *,
        chat_history: str,
        target_language: str,
        tone: str,
        character: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> OutboundTranslation:
        """Client English -> community language, in tone + character voice.
        `target_language` of "auto" means: match whatever language the
        community member has been writing in (from `chat_history`)."""

    @abstractmethod
    async def generate_session_report(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        """Full transcript -> summary / needs vs offers / sentiment / profile JSON."""

    @abstractmethod
    async def generate_satisfaction_analysis(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        """Full transcript -> community satisfaction JSON (level, score, trend,
        positives/concerns/unmet needs/recommendations)."""

    @abstractmethod
    async def generate_member_summary(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        """Full transcript -> a community member's ongoing profile summary
        for the client dashboard's community roster — framed as "who this
        person is and what they need," not a single session's recap."""


class VideoProvider(ABC):
    """Video-conferencing room/token provider for the Meeting Room's live
    calls. `create_room`/`end_room` manage the room's lifecycle server-side;
    `generate_access_token` mints a short-lived, per-participant join
    credential — no participant ever sees the provider's API key/secret."""

    @abstractmethod
    async def create_room(self, room_name: str) -> None:
        """Idempotent: safe to call even if the room already exists."""

    @abstractmethod
    async def generate_access_token(
        self, *, room_name: str, participant_identity: str, participant_name: str, ttl_seconds: int
    ) -> str:
        """Returns a signed token a client can use to join `room_name`."""

    @abstractmethod
    async def end_room(self, room_name: str) -> None:
        """Force-disconnects every participant and closes the room."""
