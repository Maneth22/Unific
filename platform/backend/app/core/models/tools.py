"""Tools Registry — the catalog of which concrete service implementations
exist for each pluggable slot in the app (WhatsApp sender, WhatsApp
auto-reply generator, the comms agent, the video/LiveKit provider, and the
live-meeting STT/TTS/translation backends), and the staff-set system-wide
default for each slot.

Two tables, two different jobs:

- `ToolCatalogEntry` is the admin-visible METADATA layer — what's known to
  exist, its display name, which pip package backs it, and whether staff
  have switched it off. It is deliberately NOT the thing that decides
  whether a `tool_key` actually works — see
  `app.core.services.tools_registry`'s code-level `_REGISTRY` for that.
  Package version is never stored here; it's read live via
  `importlib.metadata.version(...)` at query time (see `tools_service.py`)
  so it can never drift from what's actually installed.
- `ToolGlobalSelection` is the staff-editable system-wide default. For
  `whatsapp_send`/`video_provider` (singleton platform infra — one WhatsApp
  Business number, one LiveKit deployment) it is the ONLY selection that
  ever exists, at every call site, for every identity. For the five slots
  that cascade per the identity tree (`reply_generator`, `comms_agent`,
  `meeting_stt`, `meeting_tts`, `meeting_translation`) it is instead the
  root-of-cascade default — the same role `profiles.services.ROOT_DEFAULTS`
  plays for reply role/tone/etc, just admin-editable instead of a Python
  literal (see `app.profiles.services._compute_effective`).

`language` is the literal sentinel `"*"` for the five single-choice slots
(`Permission`'s own_*/effective_* string columns don't have a language
dimension) and an ISO 639-1 code for `meeting_stt`/`meeting_tts` rows —
kept in the same table rather than a "global" and a "global per language"
table, since every row is still just "(slot, [language]) -> tool_key",
same shape either way.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow
from app.database import Base

# Sentinel `language` value for the five slots with no per-language
# dimension — never collides with a real ISO 639-1 code.
GLOBAL_LANGUAGE = "*"


class ToolSlot(str, enum.Enum):
    whatsapp_send = "whatsapp_send"
    reply_generator = "reply_generator"
    comms_agent = "comms_agent"
    video_provider = "video_provider"
    meeting_stt = "meeting_stt"
    meeting_tts = "meeting_tts"
    meeting_translation = "meeting_translation"


# Slots with no per-client-org override — see docs/ARCHITECTURE.md's Tools
# Registry section: both are one-per-platform infra (one WhatsApp Business
# number, one LiveKit deployment), never identity-scoped. Every other slot
# cascades through profiles.permission's own_*/effective_* mechanism.
GLOBAL_ONLY_SLOTS = frozenset({ToolSlot.whatsapp_send, ToolSlot.video_provider})

# Slots keyed per-language (meeting_stt/meeting_tts) vs. single-choice
# (everything else) — drives whether a ToolGlobalSelection/Permission field
# is a plain string or a {language: tool_key} map.
PER_LANGUAGE_SLOTS = frozenset({ToolSlot.meeting_stt, ToolSlot.meeting_tts})


class ToolCatalogEntry(Base):
    __tablename__ = "tool_catalog_entry"
    # No separate slot index needed — slot is the leading column of the
    # composite primary key below, already indexed.
    __table_args__ = {"schema": "core"}

    # Composite PK — tool_key alone is NOT unique across slots: "gemini" is
    # a valid tool_key under reply_generator, comms_agent, AND
    # meeting_translation; "mock" under whatsapp_send, comms_agent, AND
    # video_provider; "azure"/"google" under both meeting_stt and
    # meeting_tts. Every lookup/FK-shaped reference elsewhere in this
    # feature keys on (slot, tool_key) together, never tool_key alone.
    slot: Mapped[ToolSlot] = mapped_column(Enum(ToolSlot, name="tool_slot"), primary_key=True)
    tool_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # Looked up live via importlib.metadata.version(package_name) at read
    # time (tools_service.get_catalog) — never hand-entered/stored, so it
    # can't drift from what's actually installed on a given deploy.
    package_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Staff off-switch, no deploy needed — a disabled tool_key can't be
    # selected via set_global_selection/set_own_selection (see
    # tools_service.py) even though its factory is still registered in
    # code; existing selections already pointing at it are left alone
    # (disabling is a "stop offering this going forward" action, not a
    # forced migration of whoever already picked it).
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ToolGlobalSelection(Base):
    __tablename__ = "tool_global_selection"
    __table_args__ = {"schema": "core"}

    slot: Mapped[ToolSlot] = mapped_column(Enum(ToolSlot, name="tool_slot"), primary_key=True)
    language: Mapped[str] = mapped_column(String(20), primary_key=True, default=GLOBAL_LANGUAGE)
    tool_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Only meaningful for slot=meeting_tts — a provider-specific voice id
    # (e.g. Azure's "hi-IN-SwaraNeural", an ElevenLabs voice id), mirroring
    # the "voice" field settings.live_agents_tts_provider_map's per-language
    # entries already carry. NULL for every other slot.
    voice: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
