"""Plugin catalog + org entitlement API. `client_router` lets an org see
its own entitlements (directive item 6); `router` is the staff/admin
plugin-management surface (directive item 7) — fully audited via
`app.plugins.services`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.dependencies import require_admin
from app.database import get_db
from app.orgs.security import get_current_org_user
from app.plugins import schemas, services

# ============================= Client (org) routes =============================

client_router = APIRouter(prefix="/api/plugins/client", tags=["plugins:client"])


@client_router.get("/entitlements", response_model=list[schemas.EntitlementOut])
async def client_list_entitlements(org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    return await services.list_org_entitlements(db, org_user.org_id)


@client_router.get("/catalog", response_model=list[schemas.PluginCatalogOut])
async def client_list_catalog(db: AsyncSession = Depends(get_db)):
    return await services.list_catalog(db, active_only=True)


# ============================= Staff/admin routes =============================

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("/catalog", response_model=list[schemas.PluginCatalogOut])
async def list_catalog(staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await services.list_catalog(db)


@router.patch("/catalog/{plugin_key}", response_model=schemas.PluginCatalogOut)
async def set_catalog_entry_active(
    plugin_key: str, req: schemas.CatalogToggleRequest, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    try:
        catalog = await services.set_catalog_entry_active(db, plugin_key, is_active=req.is_active, actor_id=staff.id)
    except services.PluginsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return catalog


@router.get("/orgs/{org_id}/entitlements", response_model=list[schemas.EntitlementOut])
async def staff_list_org_entitlements(org_id: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await services.list_org_entitlements(db, org_id)


@router.post("/orgs/{org_id}/entitlements", response_model=schemas.EntitlementOut, status_code=201)
async def grant_entitlement(
    org_id: str, req: schemas.GrantEntitlementRequest, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    try:
        entitlement = await services.grant_entitlement(
            db, org_id=org_id, plugin_key=req.plugin_key, limits_override=req.limits_override, actor_id=staff.id
        )
    except services.PluginsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return entitlement


@router.post("/orgs/{org_id}/entitlements/{plugin_key}/revoke", response_model=schemas.EntitlementOut)
async def revoke_entitlement(org_id: str, plugin_key: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        entitlement = await services.revoke_entitlement(db, org_id=org_id, plugin_key=plugin_key, actor_id=staff.id)
    except services.PluginsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return entitlement


@router.post("/orgs/{org_id}/entitlements/{plugin_key}/suspend", response_model=schemas.EntitlementOut)
async def suspend_entitlement(org_id: str, plugin_key: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        entitlement = await services.suspend_entitlement(db, org_id=org_id, plugin_key=plugin_key, actor_id=staff.id)
    except services.PluginsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return entitlement


@router.patch("/orgs/{org_id}/entitlements/{plugin_key}", response_model=schemas.EntitlementOut)
async def set_limits_override(
    org_id: str, plugin_key: str, req: schemas.SetLimitsOverrideRequest,
    staff=Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    try:
        entitlement = await services.set_limits_override(
            db, org_id=org_id, plugin_key=plugin_key, limits_override=req.limits_override, actor_id=staff.id
        )
    except services.PluginsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return entitlement
