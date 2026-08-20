"""Pydantic shapes for the Tools Registry API (`app.core.tools_router`) —
mirrors `meeting_room.schemas.ConfigBoardOut`/`ConfigBoardUpdate`'s
own_*/effective_* distinction, generalized across all seven slots.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.core.models.tools import ToolSlot


class ToolCatalogEntryOut(BaseModel):
    slot: str
    tool_key: str
    display_name: str
    description: str
    package_name: str | None
    package_version: str | None
    is_enabled: bool


class CatalogEntryEnabledUpdate(BaseModel):
    is_enabled: bool


class GlobalSelectionOut(BaseModel):
    slot: str
    language: str
    tool_key: str
    voice: str | None = None


class GlobalSelectionUpdate(BaseModel):
    tool_key: str
    # "*" (the default) for the five single-choice slots; an ISO 639-1 code
    # for meeting_stt/meeting_tts.
    language: str = "*"
    # Required (and only meaningful) for slot=meeting_tts.
    voice: str | None = None


class OwnSelectionUpdate(BaseModel):
    """The one write shape both the staff and client identity-tools
    endpoints use — sets (or, with `tool_key=None`, clears) one slot's
    override for one identity. Mirrors `tools_service.set_own_selection`'s
    parameters exactly."""

    slot: ToolSlot
    tool_key: str | None
    language: str | None = None
    voice: str | None = None


class IdentityToolConfigOut(BaseModel):
    identity_id: str

    reply_generator: str
    own_reply_generator: str | None
    comms_agent: str
    own_comms_agent: str | None
    meeting_translation: str
    own_meeting_translation: str | None
    meeting_stt: dict[str, str]
    own_meeting_stt: dict[str, str] | None
    meeting_tts: dict[str, dict]
    own_meeting_tts: dict[str, dict] | None
