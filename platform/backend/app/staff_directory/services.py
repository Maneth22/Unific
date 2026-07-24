"""Admin-managed staff categories and the staff directory — the Profiles
Room's "Staff" view, kept structurally separate from the client identity
tree (`app.profiles.services`) since staff are never identity-tree nodes.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.staff import StaffCategory, StaffTier, StaffUser
from app.core.services import audit_service


class StaffDirectoryError(Exception):
    pass


async def create_category(db: AsyncSession, *, name: str, description: str, staff_id: str) -> StaffCategory:
    existing = await db.execute(select(StaffCategory).where(StaffCategory.name == name))
    if existing.scalar_one_or_none() is not None:
        raise StaffDirectoryError(f"A category named '{name}' already exists")

    category = StaffCategory(name=name, description=description, created_by=staff_id)
    db.add(category)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="staff_directory.category.create",
        entity_type="staff_category",
        entity_id=category.id,
        after={"name": name},
    )
    return category


async def list_categories(db: AsyncSession) -> list[StaffCategory]:
    result = await db.execute(select(StaffCategory).order_by(StaffCategory.name))
    return list(result.scalars().all())


async def list_staff_lite(db: AsyncSession) -> list[StaffUser]:
    """Any staff account can see who else exists (id + name only) to pick
    an inbox recipient — the full directory (tier/category/active) stays
    admin-only, see `list_staff_directory`."""
    result = await db.execute(select(StaffUser).where(StaffUser.is_active.is_(True)).order_by(StaffUser.full_name))
    return list(result.scalars().all())


async def list_staff_directory(db: AsyncSession) -> list[dict]:
    """One row per staff account with its category name resolved — the
    admin's "Staff" list, joined once here rather than N+1'd per row."""
    result = await db.execute(
        select(StaffUser, StaffCategory.name)
        .outerjoin(StaffCategory, StaffUser.category_id == StaffCategory.id)
        .order_by(StaffUser.full_name)
    )
    rows = []
    for staff, category_name in result.all():
        rows.append(
            {
                "id": staff.id,
                "email": staff.email,
                "full_name": staff.full_name,
                "tier": staff.tier.value,
                "category_id": staff.category_id,
                "category_name": category_name,
                "is_active": staff.is_active,
                "created_at": staff.created_at,
            }
        )
    return rows


async def update_staff(
    db: AsyncSession,
    staff_id: str,
    *,
    actor_id: str,
    tier: str | None = None,
    category_id: str | None = None,
    is_active: bool | None = None,
) -> StaffUser:
    staff = await db.get(StaffUser, staff_id)
    if staff is None:
        raise StaffDirectoryError("Staff account not found")

    before = {"tier": staff.tier.value, "category_id": staff.category_id, "is_active": staff.is_active}

    if tier is not None:
        try:
            staff.tier = StaffTier(tier)
        except ValueError as exc:
            raise StaffDirectoryError("tier must be 'admin' or 'staff'") from exc
    if category_id is not None:
        category = await db.get(StaffCategory, category_id)
        if category is None:
            raise StaffDirectoryError("Unknown category_id")
        staff.category_id = category_id
    if is_active is not None:
        staff.is_active = is_active

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=actor_id,
        action="staff_directory.staff.update",
        entity_type="staff_user",
        entity_id=staff.id,
        before=before,
        after={"tier": staff.tier.value, "category_id": staff.category_id, "is_active": staff.is_active},
    )
    return staff
