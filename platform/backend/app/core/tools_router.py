"""Tools Registry API — staff-admin catalog/global-default management, and
the identity-scoped own_*/effective_* read/write both staff and client
admins use (staff: any identity; client: their own subtree only, via the
same `require_identity_scope` every other client-facing identity write in
this app already uses).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.client import ClientStaffUser, ClientUser
from app.core.models.common import utcnow
from app.core.models.staff import StaffUser
from app.core.models.tools import GLOBAL_ONLY_SLOTS, ToolSlot
from app.core.security.dependencies import require_admin
from app.core.services import tools_service
from app.core.tools_schemas import (
    CatalogEntryEnabledUpdate,
    GlobalSelectionOut,
    GlobalSelectionUpdate,
    IdentityToolConfigOut,
    OwnSelectionUpdate,
    ToolCatalogEntryOut,
)
from app.database import get_db
from app.profiles.security import require_identity_scope

admin = require_admin
identity_scope = require_identity_scope()


def _actor_type_for(client: ClientUser | ClientStaffUser) -> ActorType:
    return ActorType.client if isinstance(client, ClientUser) else ActorType.client_staff


async def _identity_config_out(db: AsyncSession, identity_id: str) -> IdentityToolConfigOut:
    from app.profiles.models import Permission

    perm = await db.get(Permission, identity_id)
    if perm is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return IdentityToolConfigOut(
        identity_id=identity_id,
        reply_generator=perm.effective_reply_generator_tool,
        own_reply_generator=perm.own_reply_generator_tool,
        comms_agent=perm.effective_comms_agent_tool,
        own_comms_agent=perm.own_comms_agent_tool,
        meeting_translation=perm.effective_meeting_translation_tool,
        own_meeting_translation=perm.own_meeting_translation_tool,
        meeting_stt=perm.effective_meeting_stt_tools or {},
        own_meeting_stt=perm.own_meeting_stt_tools,
        meeting_tts=perm.effective_meeting_tts_tools or {},
        own_meeting_tts=perm.own_meeting_tts_tools,
    )


# ============================= Staff routes =============================

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/catalog", response_model=list[ToolCatalogEntryOut])
async def list_catalog(
    slot: ToolSlot | None = Query(default=None), staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    return await tools_service.get_catalog(db, slot=slot)


@router.patch("/catalog/{slot}/{tool_key}", response_model=ToolCatalogEntryOut)
async def set_catalog_entry_enabled(
    slot: ToolSlot, tool_key: str, req: CatalogEntryEnabledUpdate,
    staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db),
):
    try:
        await tools_service.set_catalog_entry_enabled(
            db, slot, tool_key, is_enabled=req.is_enabled, actor_type=ActorType.staff, actor_id=staff.id
        )
    except tools_service.ToolConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    entries = await tools_service.get_catalog(db, slot=slot)
    return next(e for e in entries if e["tool_key"] == tool_key)


@router.get("/global", response_model=list[GlobalSelectionOut])
async def get_global_selections(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    rows = await tools_service.list_global_selections(db)
    return [
        GlobalSelectionOut(slot=r.slot.value, language=r.language, tool_key=r.tool_key, voice=r.voice) for r in rows
    ]


@router.put("/global/{slot}", response_model=GlobalSelectionOut)
async def update_global_selection(
    slot: ToolSlot, req: GlobalSelectionUpdate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    try:
        row = await tools_service.set_global_selection(
            db, slot=slot, tool_key=req.tool_key, language=req.language, voice=req.voice,
            actor_type=ActorType.staff, actor_id=staff.id,
        )
    except tools_service.ToolConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return GlobalSelectionOut(slot=row.slot.value, language=row.language, tool_key=row.tool_key, voice=row.voice)


@router.get("/identities/{identity_id}", response_model=IdentityToolConfigOut)
async def get_identity_tool_config(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await _identity_config_out(db, identity_id)


@router.put("/identities/{identity_id}", response_model=IdentityToolConfigOut)
async def update_identity_tool_config(
    identity_id: str, req: OwnSelectionUpdate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    try:
        await tools_service.set_own_selection(
            db, identity_id, slot=req.slot, tool_key=req.tool_key, language=req.language, voice=req.voice,
            actor_type=ActorType.staff, actor_id=staff.id,
        )
    except tools_service.ToolConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return await _identity_config_out(db, identity_id)


# ============================= Client routes =============================
# Same require_identity_scope() gate every other client-facing identity
# write in this app uses — a client (owner or staff) may configure any
# identity within their own scope, never GLOBAL_ONLY_SLOTS (whatsapp_send/
# video_provider — those aren't per-identity concepts at all, see
# tools_service.set_own_selection's own guard).

client_router = APIRouter(prefix="/api/tools/client", tags=["tools:client"])


@client_router.get("/catalog", response_model=list[ToolCatalogEntryOut])
async def client_list_catalog(
    slot: ToolSlot | None = Query(default=None), db: AsyncSession = Depends(get_db)
):
    """Unauthenticated read of the enabled catalog, filtered to the five
    cascading slots — a client admin needs to see what's selectable before
    logging into a specific identity's config, same reasoning
    `meeting_room.public_router`'s `/translation-languages` route is
    public. Never includes whatsapp_send/video_provider (see
    GLOBAL_ONLY_SLOTS) — those are never client-configurable."""
    entries = await tools_service.get_catalog(db, slot=slot, enabled_only=True)
    return [e for e in entries if e["slot"] not in {s.value for s in GLOBAL_ONLY_SLOTS}]


@client_router.get("/identities/{identity_id}", response_model=IdentityToolConfigOut)
async def client_get_identity_tool_config(
    identity_id: str, client: ClientUser | ClientStaffUser = Depends(identity_scope), db: AsyncSession = Depends(get_db)
):
    return await _identity_config_out(db, identity_id)


@client_router.put("/identities/{identity_id}", response_model=IdentityToolConfigOut)
async def client_update_identity_tool_config(
    identity_id: str, req: OwnSelectionUpdate,
    client: ClientUser | ClientStaffUser = Depends(identity_scope), db: AsyncSession = Depends(get_db),
):
    try:
        await tools_service.set_own_selection(
            db, identity_id, slot=req.slot, tool_key=req.tool_key, language=req.language, voice=req.voice,
            actor_type=_actor_type_for(client), actor_id=client.id,
        )
    except tools_service.ToolConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return await _identity_config_out(db, identity_id)
