"""Plugin entitlement business logic. `has()` is the one function every
feature code path calls to gate a paid capability — never a hardcoded
check. Admin write functions mirror `app.orgs.services`'s audit
discipline: every mutation takes `actor_id` and calls `audit_service.record`.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow
from app.core.services import audit_service
from app.plugins.models import EntitlementStatus, OrgEntitlement, PluginCatalog, PluginCategory


class PluginsError(Exception):
    pass


async def has(db: AsyncSession, org_id: str, plugin_key: str) -> bool:
    """Single indexed (composite PK) lookup, no join, no cascade. An
    absent row or a non-active status both read as not-entitled."""
    row = await db.get(OrgEntitlement, (org_id, plugin_key))
    return row is not None and row.status == EntitlementStatus.active


async def get_effective_limits(db: AsyncSession, org_id: str, plugin_key: str) -> dict:
    """`default_limits` shallow-merged with `limits_override` (override
    wins per key) — not exercised by this phase's pure-boolean gating,
    kept for `ai_reply_agent_pro`/future limit-checking phases."""
    catalog = await db.get(PluginCatalog, plugin_key)
    if catalog is None:
        return {}
    limits = dict(catalog.default_limits or {})
    entitlement = await db.get(OrgEntitlement, (org_id, plugin_key))
    if entitlement is not None and entitlement.limits_override:
        limits.update(entitlement.limits_override)
    return limits


# --- Catalog (admin) --------------------------------------------------------


async def list_catalog(db: AsyncSession, *, category: PluginCategory | None = None, active_only: bool = False) -> list[PluginCatalog]:
    query = select(PluginCatalog).order_by(PluginCatalog.category, PluginCatalog.name)
    if category is not None:
        query = query.where(PluginCatalog.category == category)
    if active_only:
        query = query.where(PluginCatalog.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def set_catalog_entry_active(db: AsyncSession, plugin_key: str, *, is_active: bool, actor_id: str) -> PluginCatalog:
    catalog = await db.get(PluginCatalog, plugin_key)
    if catalog is None:
        raise PluginsError("Plugin not found in catalog")
    before = catalog.is_active
    catalog.is_active = is_active
    await db.flush()
    await audit_service.record(
        db, actor_type=ActorType.staff, actor_id=actor_id, action="plugins.catalog.set_active",
        room=RoomName.plugins, entity_type="plugin_catalog", entity_id=plugin_key,
        before={"is_active": before}, after={"is_active": is_active},
    )
    return catalog


# --- Org entitlements (admin) ----------------------------------------------


async def list_org_entitlements(db: AsyncSession, org_id: str) -> list[OrgEntitlement]:
    result = await db.execute(select(OrgEntitlement).where(OrgEntitlement.org_id == org_id))
    return list(result.scalars().all())


async def grant_entitlement(
    db: AsyncSession, *, org_id: str, plugin_key: str, limits_override: dict | None = None, actor_id: str
) -> OrgEntitlement:
    catalog = await db.get(PluginCatalog, plugin_key)
    if catalog is None or not catalog.is_active:
        raise PluginsError("Plugin is not available in the catalog")

    row = await db.get(OrgEntitlement, (org_id, plugin_key))
    before = {"status": row.status.value} if row is not None else None
    if row is None:
        row = OrgEntitlement(org_id=org_id, plugin_key=plugin_key, limits_override=limits_override, activated_by=actor_id)
        db.add(row)
    else:
        row.status = EntitlementStatus.active
        row.activated_at = utcnow()
        row.activated_by = actor_id
        if limits_override is not None:
            row.limits_override = limits_override
    await db.flush()
    await audit_service.record(
        db, actor_type=ActorType.staff, actor_id=actor_id, action="plugins.entitlement.grant",
        room=RoomName.plugins, entity_type="org_entitlement", entity_id=f"{org_id}:{plugin_key}",
        before=before, after={"status": "active"},
    )
    return row


async def _set_status(
    db: AsyncSession, *, org_id: str, plugin_key: str, status: EntitlementStatus, action: str, actor_id: str
) -> OrgEntitlement:
    row = await db.get(OrgEntitlement, (org_id, plugin_key))
    if row is None:
        raise PluginsError("This org has no entitlement for that plugin")
    before = {"status": row.status.value}
    row.status = status
    await db.flush()
    await audit_service.record(
        db, actor_type=ActorType.staff, actor_id=actor_id, action=action,
        room=RoomName.plugins, entity_type="org_entitlement", entity_id=f"{org_id}:{plugin_key}",
        before=before, after={"status": status.value},
    )
    return row


async def revoke_entitlement(db: AsyncSession, *, org_id: str, plugin_key: str, actor_id: str) -> OrgEntitlement:
    """Sets status=cancelled — the row is kept (not deleted), preserving
    limits_override/audit history. A plugin toggle only affects the NEXT
    meeting scheduled after this call; a meeting already live keeps
    running (see app.meetings.services._mark_joined — entitlement is only
    ever checked once, at the scheduled->live transition)."""
    return await _set_status(db, org_id=org_id, plugin_key=plugin_key, status=EntitlementStatus.cancelled, action="plugins.entitlement.revoke", actor_id=actor_id)


async def suspend_entitlement(db: AsyncSession, *, org_id: str, plugin_key: str, actor_id: str) -> OrgEntitlement:
    return await _set_status(db, org_id=org_id, plugin_key=plugin_key, status=EntitlementStatus.suspended, action="plugins.entitlement.suspend", actor_id=actor_id)


async def set_limits_override(
    db: AsyncSession, *, org_id: str, plugin_key: str, limits_override: dict | None, actor_id: str
) -> OrgEntitlement:
    row = await db.get(OrgEntitlement, (org_id, plugin_key))
    if row is None:
        raise PluginsError("This org has no entitlement for that plugin")
    before = {"limits_override": row.limits_override}
    row.limits_override = limits_override
    await db.flush()
    await audit_service.record(
        db, actor_type=ActorType.staff, actor_id=actor_id, action="plugins.entitlement.set_limits_override",
        room=RoomName.plugins, entity_type="org_entitlement", entity_id=f"{org_id}:{plugin_key}",
        before=before, after={"limits_override": limits_override},
    )
    return row
