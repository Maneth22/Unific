"""The single write path into `core.audit_log`. Every service that
mutates state — staff auth, account registry, permissions, spend — calls
this instead of constructing an `AuditLog` row itself, so the shape of
an audit entry never drifts between rooms.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType, AuditLog
from app.core.models.common import RoomName


async def record(
    db: AsyncSession,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    action: str,
    room: RoomName | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    note: str = "",
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        room=room,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        note=note,
        ip_address=ip_address,
    )
    db.add(entry)
    await db.flush()
    return entry
