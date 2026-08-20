"""The Tools Registry's code-side factory registry — the authoritative
answer to "does this tool_key actually have working code behind it".

`core.tool_catalog_entry` (see `tools_service.py`) is the admin-editable
METADATA layer (display name, package info, enable/disable); it is
deliberately not consulted here for whether something can be built. This
module is code, reviewed and deployed like any other code — a brand-new
`tool_key` always needs a developer to add a factory (or, for the three
meeting-room-owned slots below, a provider function) here before it can
ever be selected, no matter what a catalog row claims.

Four slots (`whatsapp_send`, `reply_generator`, `comms_agent`,
`video_provider`) are registered directly in `_REGISTRY` below, exactly
mirroring what `app.core.providers.factory` used to hardcode per env var —
same concrete classes, same lazy imports, just keyed by `tool_key` instead
of by `settings.*_provider`.

The other three (`meeting_stt`, `meeting_tts`, `meeting_translation`) are
owned by `app.meeting_room.live_agents` — `core` must never import from a
room package (see `app/core/providers/base.py`'s own docstring on this),
so this module only tracks which `tool_key`s are valid for those three
slots (for catalog/validation purposes); actual instantiation happens
entirely inside `meeting_room.live_agents.providers`
(`is_stt_language_supported`/`get_tts_for_language`) and a small sibling
registry for the live-translation backend. Keep the three `_MEETING_*_KEYS`
sets below in sync with those modules' own factory dicts by hand — there's
no way to derive one from the other without the import this module is
specifically avoiding.
"""
from __future__ import annotations

from typing import Callable

from app.core.models.tools import PER_LANGUAGE_SLOTS, ToolSlot


class ToolNotRegisteredError(Exception):
    """`tool_key` has no matching factory (or, for the three meeting-room
    slots, isn't in the known-valid set) for its slot — always raised,
    never silently substituted. Can only happen if a catalog/selection row
    references a `tool_key` no deployed code actually knows how to build
    (e.g. a manual DB edit, or a rollback that removed the adapter)."""


def _lazy(module_path: str, class_name: str) -> Callable[[], object]:
    def _build() -> object:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, class_name)()

    return _build


_REGISTRY: dict[ToolSlot, dict[str, Callable[[], object]]] = {
    ToolSlot.whatsapp_send: {
        "cloud_api": _lazy("app.core.providers.cloud_api_whatsapp", "CloudAPIWhatsAppProvider"),
        "mock": _lazy("app.core.providers.mock_whatsapp", "MockWhatsAppProvider"),
    },
    ToolSlot.reply_generator: {
        "gemini": _lazy("app.agents.whatsapp_community.providers.gemini_reply_generator", "GeminiReplyGenerator"),
        "stub": _lazy("app.agents.whatsapp_community.providers.stub_reply_generator", "StubReplyGenerator"),
    },
    ToolSlot.comms_agent: {
        "gemini": _lazy("app.agents.whatsapp_community.providers.gemini_comms_agent", "GeminiCommsAgent"),
        "mock": _lazy("app.agents.whatsapp_community.providers.mock_comms_agent", "MockCommsAgent"),
    },
    ToolSlot.video_provider: {
        "livekit": _lazy("app.core.providers.livekit_video_provider", "LiveKitVideoProvider"),
        "mock": _lazy("app.core.providers.mock_video_provider", "MockVideoProvider"),
    },
}

# The three meeting-room-owned slots — no factories here, just the set of
# tool_keys `meeting_room.live_agents` actually knows how to build. Must
# match `live_agents/providers.py`'s STT support ("google" is the only
# key `is_stt_language_supported` ever returns True for) and
# `TTS_FACTORIES` keys, and `live_agents/translation_backends.py`'s
# registry, respectively.
# Google-only is a deliberate product decision (Deepgram/Azure/OpenAI/
# ElevenLabs were removed) — not a temporary state.
_MEETING_STT_KEYS = frozenset({"google"})
_MEETING_TTS_KEYS = frozenset({"google"})
_MEETING_TRANSLATION_KEYS = frozenset({"gemini"})

_MEETING_ROOM_SLOT_KEYS: dict[ToolSlot, frozenset[str]] = {
    ToolSlot.meeting_stt: _MEETING_STT_KEYS,
    ToolSlot.meeting_tts: _MEETING_TTS_KEYS,
    ToolSlot.meeting_translation: _MEETING_TRANSLATION_KEYS,
}


def get_factory(slot: ToolSlot, tool_key: str) -> Callable[[], object]:
    """Only valid for the four `core`-registered slots — the three
    meeting-room slots are never instantiated through this module (see
    module docstring); calling this for one of them is a programming
    error, not a normal "unregistered tool" case."""
    if slot in _MEETING_ROOM_SLOT_KEYS:
        raise ToolNotRegisteredError(
            f"slot={slot!r} is owned by app.meeting_room.live_agents — it has no core-registered "
            "factory; construct it via that package's own provider lookup instead."
        )
    try:
        return _REGISTRY[slot][tool_key]
    except KeyError:
        raise ToolNotRegisteredError(f"No factory registered for slot={slot!r} tool_key={tool_key!r}") from None


def is_registered(slot: ToolSlot, tool_key: str) -> bool:
    """The check `tools_service`'s write paths use before accepting a
    selection — works uniformly across all seven slots, unlike
    `get_factory` (which only ever constructs the four core ones)."""
    if slot in _MEETING_ROOM_SLOT_KEYS:
        return tool_key in _MEETING_ROOM_SLOT_KEYS[slot]
    return tool_key in _REGISTRY.get(slot, {})


def registered_tool_keys(slot: ToolSlot) -> list[str]:
    if slot in _MEETING_ROOM_SLOT_KEYS:
        return sorted(_MEETING_ROOM_SLOT_KEYS[slot])
    return list(_REGISTRY.get(slot, {}).keys())


def is_per_language(slot: ToolSlot) -> bool:
    return slot in PER_LANGUAGE_SLOTS
