"""Tools Registry — the `db`-aware read/write/resolve layer over
`core.tool_catalog_entry` / `core.tool_global_selection` and, for the five
cascading slots, `profiles.permission`'s `own_*`/`effective_*` columns.

Three jobs, three groups of functions:

1. Catalog (`get_catalog`) — what's known to exist and enabled, with a
   live-read package version.
2. Write paths (`set_global_selection`, `set_own_selection`) — validate
   against both the catalog (`is_enabled`) and the code registry
   (`tools_registry.is_registered`) before ever touching a row, so a
   selection can never point at something that doesn't actually work.
3. Read/resolve paths (`resolve_effective_tools`, `get_global_tool`,
   `get_tool_for_identity`) — turn a slot (+ identity, for cascading
   slots) into a ready-to-use instance, via an instance cache keyed by
   `(slot, tool_key)` (`get_tool_instance`) rather than `factory.py`'s old
   per-slot `@lru_cache`, since two different identities can now resolve
   the same slot to two different tools at once.

`meeting_stt`/`meeting_tts`/`meeting_translation` are resolved here only as
far as *which tool_key* — `app.meeting_room.live_agents` owns actually
building an STT/TTS/translation-backend instance from that key (see
`tools_registry.py`'s module docstring for why: `core` must never import a
room package).
"""
from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import utcnow
from app.core.models.tools import GLOBAL_LANGUAGE, GLOBAL_ONLY_SLOTS, ToolCatalogEntry, ToolGlobalSelection, ToolSlot
from app.core.services import audit_service, tools_registry

logger = logging.getLogger(__name__)


class ToolConfigError(Exception):
    """A write attempt referenced a `tool_key` that's absent from the
    catalog, disabled, or not code-registered — never silently
    substituted/ignored."""


# Ultimate fallback if core.tool_global_selection has no row yet for a
# slot (e.g. a fresh test DB that skipped the seed migration's data step)
# — matches app.config.Settings' own field defaults exactly, so a missing
# row degrades to the same behavior the old .env-only system had, never to
# an arbitrary/undefined choice.
_HARDCODED_FALLBACK: dict[ToolSlot, str] = {
    ToolSlot.whatsapp_send: "mock",
    ToolSlot.reply_generator: "stub",
    ToolSlot.comms_agent: "gemini",
    ToolSlot.video_provider: "mock",
    ToolSlot.meeting_translation: "gemini",
}


@dataclass(frozen=True)
class ToolGlobalDefaults:
    """The staff-set system-wide default for the five cascading slots —
    loaded once per `profiles.services.recompute_cascade`/`create_identity`
    call (not per descendant) and passed into `_compute_effective` as the
    root-of-cascade default, replacing `ROOT_DEFAULTS` for these fields
    only."""

    reply_generator_tool: str
    comms_agent_tool: str
    meeting_translation_tool: str
    meeting_stt_tools: dict[str, str] = field(default_factory=dict)
    # {language: {"provider": tool_key, "voice": voice_id}} — a provider
    # choice alone isn't enough to synthesize speech, matching the shape
    # settings.live_agents_tts_provider_map already used.
    meeting_tts_tools: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectiveToolConfig:
    """One identity's (or, for a staff meeting, the system's) fully
    resolved tool choices — what `meeting_room.services._mark_joined` and
    `app.agents.whatsapp_community.orchestrator.receive_inbound_message`
    actually act on."""

    reply_generator: str
    comms_agent: str
    meeting_translation: str
    meeting_stt: dict[str, str] = field(default_factory=dict)
    meeting_tts: dict[str, dict] = field(default_factory=dict)


# --- Global selection reads/writes ----------------------------------------

async def _global_rows(db: AsyncSession, slot: ToolSlot | None = None) -> list[ToolGlobalSelection]:
    stmt = select(ToolGlobalSelection)
    if slot is not None:
        stmt = stmt.where(ToolGlobalSelection.slot == slot)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_global_selections(db: AsyncSession, slot: ToolSlot | None = None) -> list[ToolGlobalSelection]:
    """Public read entry point for `tools_router.get_global_selections` —
    `_global_rows` stays "private" (module-internal helper name) since
    `load_global_defaults` is the one other thing that calls it."""
    return await _global_rows(db, slot)


async def get_global_tool_selection(db: AsyncSession, slot: ToolSlot, language: str = GLOBAL_LANGUAGE) -> str:
    row = await db.get(ToolGlobalSelection, (slot, language))
    if row is not None:
        return row.tool_key
    fallback = _HARDCODED_FALLBACK.get(slot)
    if fallback is not None:
        logger.warning("no core.tool_global_selection row for slot=%r language=%r — using hardcoded fallback %r",
                        slot, language, fallback)
        return fallback
    raise ToolConfigError(f"No global selection (and no fallback) for slot={slot!r} language={language!r}")


async def load_global_defaults(db: AsyncSession) -> ToolGlobalDefaults:
    """One query, folded into the dataclass `profiles.services` needs for
    the root-of-cascade case. Missing rows degrade per-field to
    `_HARDCODED_FALLBACK`/an empty map, never raise — this is the
    default-of-last-resort a brand-new identity tree bottoms out on."""
    rows = await _global_rows(db)
    scalar: dict[ToolSlot, str] = {}
    stt: dict[str, str] = {}
    tts: dict[str, dict] = {}
    for row in rows:
        if row.slot == ToolSlot.meeting_stt:
            stt[row.language] = row.tool_key
        elif row.slot == ToolSlot.meeting_tts:
            tts[row.language] = {"provider": row.tool_key, "voice": row.voice}
        else:
            scalar[row.slot] = row.tool_key
    return ToolGlobalDefaults(
        reply_generator_tool=scalar.get(ToolSlot.reply_generator, _HARDCODED_FALLBACK[ToolSlot.reply_generator]),
        comms_agent_tool=scalar.get(ToolSlot.comms_agent, _HARDCODED_FALLBACK[ToolSlot.comms_agent]),
        meeting_translation_tool=scalar.get(
            ToolSlot.meeting_translation, _HARDCODED_FALLBACK[ToolSlot.meeting_translation]
        ),
        meeting_stt_tools=stt,
        meeting_tts_tools=tts,
    )


async def _validate_selectable(slot: ToolSlot, tool_key: str, db: AsyncSession) -> None:
    if not tools_registry.is_registered(slot, tool_key):
        raise ToolConfigError(f"{tool_key!r} is not a registered implementation for slot {slot.value!r}")
    entry = await db.get(ToolCatalogEntry, (slot, tool_key))
    if entry is None:
        raise ToolConfigError(f"{tool_key!r} is not catalogued under slot {slot.value!r}")
    if not entry.is_enabled:
        raise ToolConfigError(f"{tool_key!r} is currently disabled in the tool catalog")


async def set_global_selection(
    db: AsyncSession,
    *,
    slot: ToolSlot,
    tool_key: str,
    language: str = GLOBAL_LANGUAGE,
    voice: str | None = None,
    actor_type: ActorType,
    actor_id: str | None,
) -> ToolGlobalSelection:
    """`voice` is only meaningful (and required) for `slot=meeting_tts` —
    a provider choice alone doesn't pick a synthesized voice. Ignored for
    every other slot."""
    if slot == ToolSlot.meeting_tts and not voice:
        raise ToolConfigError("meeting_tts requires a voice id alongside the provider tool_key")
    await _validate_selectable(slot, tool_key, db)
    row = await db.get(ToolGlobalSelection, (slot, language))
    before = row.tool_key if row is not None else None
    if row is None:
        row = ToolGlobalSelection(slot=slot, language=language, tool_key=tool_key)
        db.add(row)
    else:
        row.tool_key = tool_key
    row.voice = voice if slot == ToolSlot.meeting_tts else None
    row.updated_by_staff_id = actor_id if actor_type == ActorType.staff else None
    row.updated_at = utcnow()
    await db.flush()

    await audit_service.record(
        db, actor_type=actor_type, actor_id=actor_id, action="tools.global_selection.set",
        entity_type="tool_global_selection", entity_id=f"{slot.value}:{language}",
        before={"tool_key": before} if before else None, after={"tool_key": tool_key, "voice": row.voice},
    )

    if slot not in GLOBAL_ONLY_SLOTS:
        # This slot cascades — every root identity with no own_* override
        # inherits this new default. Lazy import: profiles.services
        # imports this module (load_global_defaults), so a module-level
        # import here would be circular.
        from app.profiles.models import Identity
        from app.profiles.services import recompute_cascade

        result = await db.execute(select(Identity.id).where(Identity.parent_id.is_(None)))
        for root_id in result.scalars().all():
            await recompute_cascade(db, root_id)

    return row


# --- Catalog ---------------------------------------------------------------

def _package_version(package_name: str | None) -> str | None:
    if not package_name:
        return None
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


async def get_catalog(db: AsyncSession, *, slot: ToolSlot | None = None, enabled_only: bool = False) -> list[dict]:
    stmt = select(ToolCatalogEntry)
    if slot is not None:
        stmt = stmt.where(ToolCatalogEntry.slot == slot)
    if enabled_only:
        stmt = stmt.where(ToolCatalogEntry.is_enabled.is_(True))
    result = await db.execute(stmt.order_by(ToolCatalogEntry.slot, ToolCatalogEntry.tool_key))
    return [
        {
            "tool_key": entry.tool_key,
            "slot": entry.slot.value,
            "display_name": entry.display_name,
            "description": entry.description,
            "package_name": entry.package_name,
            "package_version": _package_version(entry.package_name),
            "is_enabled": entry.is_enabled,
        }
        for entry in result.scalars().all()
    ]


async def set_catalog_entry_enabled(
    db: AsyncSession, slot: ToolSlot, tool_key: str, *, is_enabled: bool, actor_type: ActorType, actor_id: str | None
) -> ToolCatalogEntry:
    entry = await db.get(ToolCatalogEntry, (slot, tool_key))
    if entry is None:
        raise ToolConfigError(f"{tool_key!r} is not catalogued under slot {slot.value!r}")
    before = entry.is_enabled
    entry.is_enabled = is_enabled
    await db.flush()
    await audit_service.record(
        db, actor_type=actor_type, actor_id=actor_id, action="tools.catalog_entry.set_enabled",
        entity_type="tool_catalog_entry", entity_id=f"{slot.value}:{tool_key}",
        before={"is_enabled": before}, after={"is_enabled": is_enabled},
    )
    return entry


# --- Per-identity (own_*/effective_*) reads/writes --------------------------

# slot -> (own_field_name, effective_field_name) on profiles.permission.Permission
_SCALAR_FIELD_MAP: dict[ToolSlot, tuple[str, str]] = {
    ToolSlot.reply_generator: ("own_reply_generator_tool", "effective_reply_generator_tool"),
    ToolSlot.comms_agent: ("own_comms_agent_tool", "effective_comms_agent_tool"),
    ToolSlot.meeting_translation: ("own_meeting_translation_tool", "effective_meeting_translation_tool"),
}
_MAP_FIELD_MAP: dict[ToolSlot, tuple[str, str]] = {
    ToolSlot.meeting_stt: ("own_meeting_stt_tools", "effective_meeting_stt_tools"),
    ToolSlot.meeting_tts: ("own_meeting_tts_tools", "effective_meeting_tts_tools"),
}


async def resolve_effective_tools(db: AsyncSession, identity_id: str | None) -> EffectiveToolConfig:
    """`identity_id=None` — a `meeting_kind="staff"` meeting, or any other
    caller with no identity in scope — reads the staff-global row directly.
    Otherwise a plain read of `Permission`'s already-cascaded `effective_*`
    columns: O(1), no live tree walk (matches `Permission`'s own "never
    recomputed on the hot path" contract)."""
    if identity_id is None:
        defaults = await load_global_defaults(db)
        return EffectiveToolConfig(
            reply_generator=defaults.reply_generator_tool,
            comms_agent=defaults.comms_agent_tool,
            meeting_translation=defaults.meeting_translation_tool,
            meeting_stt=dict(defaults.meeting_stt_tools),
            meeting_tts=dict(defaults.meeting_tts_tools),
        )

    from app.profiles.models import Permission

    perm = await db.get(Permission, identity_id)
    if perm is None:
        logger.warning("resolve_effective_tools: no Permission row for identity_id=%r — using global defaults", identity_id)
        return await resolve_effective_tools(db, None)
    return EffectiveToolConfig(
        reply_generator=perm.effective_reply_generator_tool,
        comms_agent=perm.effective_comms_agent_tool,
        meeting_translation=perm.effective_meeting_translation_tool,
        meeting_stt=dict(perm.effective_meeting_stt_tools or {}),
        meeting_tts=dict(perm.effective_meeting_tts_tools or {}),
    )


async def set_own_selection(
    db: AsyncSession,
    identity_id: str,
    *,
    slot: ToolSlot,
    tool_key: str | None,
    language: str | None = None,
    voice: str | None = None,
    actor_type: ActorType,
    actor_id: str | None,
):
    """`tool_key=None` clears the override for this identity/language
    (inherit from parent/global default again). For the two per-language
    slots this is a read-modify-write on one language key of the JSONB
    map, not a wholesale replace — a client overriding just `si` must not
    silently drop whatever `en`/`hi` they (or their parent) already had.
    `voice` is only meaningful (and required when `tool_key` is set) for
    `slot=meeting_tts` — a provider choice alone doesn't pick a
    synthesized voice."""
    if slot in GLOBAL_ONLY_SLOTS:
        raise ToolConfigError(f"{slot.value!r} has no per-identity override — it is staff-global only")
    if slot == ToolSlot.meeting_tts and tool_key is not None and not voice:
        raise ToolConfigError("meeting_tts requires a voice id alongside the provider tool_key")
    if tool_key is not None:
        await _validate_selectable(slot, tool_key, db)

    from app.profiles.models import Permission
    from app.profiles.services import update_own_permission

    if slot in _MAP_FIELD_MAP:
        if not language:
            raise ToolConfigError(f"slot={slot.value!r} requires a language")
        own_field, _ = _MAP_FIELD_MAP[slot]
        perm = await db.get(Permission, identity_id)
        if perm is None:
            raise ToolConfigError("Identity not found")
        current = dict(getattr(perm, own_field) or {})
        if tool_key is None:
            current.pop(language, None)
        elif slot == ToolSlot.meeting_tts:
            current[language] = {"provider": tool_key, "voice": voice}
        else:
            current[language] = tool_key
        return await update_own_permission(
            db, identity_id, actor_type=actor_type, actor_id=actor_id, **{own_field: current or None}
        )

    own_field, _ = _SCALAR_FIELD_MAP[slot]
    return await update_own_permission(
        db, identity_id, actor_type=actor_type, actor_id=actor_id, **{own_field: tool_key}
    )


# --- Instance resolution/cache ----------------------------------------------

_instance_cache: dict[tuple[ToolSlot, str], object] = {}


def clear_instance_cache() -> None:
    """Test-only escape hatch — production code never needs this (a
    `(slot, tool_key)` entry is permanently valid once built, see
    `get_tool_instance`'s docstring), but a test that monkeypatches
    `settings` between runs (e.g. LiveKit credentials) needs a clean slate
    so it isn't handed a stale cached instance built under the old
    settings."""
    _instance_cache.clear()


def get_tool_instance(slot: ToolSlot, tool_key: str) -> object:
    """Only valid for the four core-registered slots (`whatsapp_send`,
    `reply_generator`, `comms_agent`, `video_provider`) — see
    `tools_registry.py`'s module docstring for why the three meeting-room
    slots are never instantiated here. Cached by `(slot, tool_key)`, not
    `(slot)`: switching which tool_key an identity resolves to next time
    never reconstructs anything for a tool_key still in use elsewhere, and
    needs no invalidation — each entry is permanently valid once built,
    same as the stateless/credential-holding clients `factory.py`'s old
    `@lru_cache` singletons already were."""
    key = (slot, tool_key)
    instance = _instance_cache.get(key)
    if instance is None:
        factory = tools_registry.get_factory(slot, tool_key)
        instance = factory()
        _instance_cache[key] = instance
    return instance


async def get_global_tool(db: AsyncSession, slot: ToolSlot) -> object:
    """Replaces `factory.get_whatsapp_provider()`/`get_video_provider()`.
    For `video_provider`, also reproduces the old factory's misconfiguration
    guard-rails (LiveKit credentials set but VIDEO_PROVIDER not selected)."""
    tool_key = await get_global_tool_selection(db, slot)
    if slot == ToolSlot.video_provider and tool_key != "livekit":
        from app.config import settings

        if settings.livekit_url or settings.livekit_api_key or settings.livekit_api_secret:
            logger.warning(
                "LiveKit credentials are set but the video_provider tool selection is %r (not "
                "'livekit') — falling back to MockVideoProvider, which mints fake tokens.", tool_key,
            )
        if settings.is_production:
            logger.error(
                "Running in production with video_provider=%r — every meeting join will receive a "
                "fake MockVideoProvider token.", tool_key,
            )
    return get_tool_instance(slot, tool_key)


async def get_tool_for_identity(db: AsyncSession, slot: ToolSlot, identity_id: str | None) -> object:
    """Replaces `factory.get_reply_generator()`/`get_comms_agent()`, now
    resolved per-identity instead of one process-wide singleton. Only
    valid for `reply_generator`/`comms_agent` — `meeting_stt`/`meeting_tts`/
    `meeting_translation` resolve through `resolve_effective_tools` and are
    instantiated by `app.meeting_room.live_agents` itself."""
    cfg = await resolve_effective_tools(db, identity_id)
    tool_key = getattr(cfg, slot.value)
    return get_tool_instance(slot, tool_key)
