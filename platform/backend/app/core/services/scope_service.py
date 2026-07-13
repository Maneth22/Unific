"""Materialized-path helpers for the Task 2 identity tree. This is the
one place `profiles.identity.path` is read/written directly — everything
else (permission cascade, the gate, client-dashboard scoping, and later
the Meeting Room's WhatsApp routing) calls through here instead of
constructing path logic of its own.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PATH_SEPARATOR = "."


def child_path(parent_path: str | None, node_id: str) -> str:
    return f"{parent_path}{PATH_SEPARATOR}{node_id}" if parent_path else node_id


async def is_ancestor_or_self(db: AsyncSession, *, root_id: str, target_id: str) -> bool:
    """True if `root_id` is `target_id` itself or one of its ancestors —
    the check a client-dashboard scope guard runs on every request."""
    if root_id == target_id:
        return True
    result = await db.execute(
        text(
            "SELECT 1 FROM profiles.identity AS root, profiles.identity AS target "
            "WHERE root.id = :root_id AND target.id = :target_id "
            "AND (target.path = root.path OR target.path LIKE root.path || '.%') "
            "LIMIT 1"
        ),
        {"root_id": root_id, "target_id": target_id},
    )
    return result.first() is not None


async def descendant_ids(db: AsyncSession, root_id: str, include_self: bool = True) -> list[str]:
    self_clause = "OR d.path = root.path" if include_self else ""
    result = await db.execute(
        text(
            "SELECT d.id FROM profiles.identity AS root, profiles.identity AS d "
            "WHERE root.id = :root_id "
            f"AND (d.path LIKE root.path || '.%' {self_clause}) "
            "ORDER BY d.path"
        ),
        {"root_id": root_id},
    )
    return [row[0] for row in result.all()]


async def ancestor_ids(db: AsyncSession, node_id: str, include_self: bool = False) -> list[str]:
    """Ancestor ids in root-to-node order — used to walk parent-first
    when recomputing effective permissions."""
    result = await db.execute(
        text("SELECT path FROM profiles.identity WHERE id = :node_id"),
        {"node_id": node_id},
    )
    row = result.first()
    if row is None:
        return []
    parts = row[0].split(PATH_SEPARATOR)
    if not include_self:
        parts = parts[:-1]
    return parts


async def reparent_subtree(db: AsyncSession, node_id: str, new_parent_path: str | None) -> None:
    """Rewrites `path` for `node_id` and every descendant after a
    parent change. Called by `identity_service.move_subtree`, which is
    responsible for also triggering a permission-cascade recompute
    afterwards."""
    result = await db.execute(
        text("SELECT path FROM profiles.identity WHERE id = :node_id"),
        {"node_id": node_id},
    )
    row = result.first()
    if row is None:
        raise ValueError("Identity not found")
    old_path = row[0]
    new_path = child_path(new_parent_path, node_id)

    await db.execute(
        text(
            "UPDATE profiles.identity "
            "SET path = :new_path || substring(path from :old_len) "
            "WHERE path = :old_path OR path LIKE :old_path || '.%'"
        ),
        {"new_path": new_path, "old_len": len(old_path) + 1, "old_path": old_path},
    )
