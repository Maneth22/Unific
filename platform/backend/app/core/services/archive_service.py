"""The three-shelf Archive Locker workflow, shared by every room. An item
moves between lockers by its `room` field changing hands, going through
Transfer (outgoing, still owned by the source room) then Receiving
(incoming, now owned by the target room, pending review) before it is
ever promoted into the target's Operational Library. Nothing is ever
auto-accepted.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.archive import ArchiveItem, ArchiveItemStatus, ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow
from app.core.services import audit_service


class ArchiveWorkflowError(Exception):
    pass


async def create_item(
    db: AsyncSession,
    *,
    room: RoomName,
    title: str,
    actor_type: ActorType,
    actor_id: str | None,
    description: str = "",
    item_type: str = "document",
    content: dict | None = None,
    approved_for_auto_reply: bool = False,
) -> ArchiveItem:
    item = ArchiveItem(
        room=room,
        shelf=ArchiveShelf.operational_library,
        status=ArchiveItemStatus.active,
        title=title,
        description=description,
        item_type=item_type,
        content=content or {},
        approved_for_auto_reply=approved_for_auto_reply,
    )
    db.add(item)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="archive.item.create",
        room=room,
        entity_type="archive_item",
        entity_id=item.id,
        after={"title": title, "shelf": ArchiveShelf.operational_library.value},
    )
    return item


async def list_shelf(db: AsyncSession, room: RoomName, shelf: ArchiveShelf) -> list[ArchiveItem]:
    result = await db.execute(
        select(ArchiveItem).where(ArchiveItem.room == room, ArchiveItem.shelf == shelf).order_by(ArchiveItem.updated_at.desc())
    )
    return list(result.scalars().all())


async def propose_transfer(
    db: AsyncSession, item_id: str, target_room: RoomName, *, actor_type: ActorType, actor_id: str | None
) -> ArchiveItem:
    item = await _require_item(db, item_id)
    if item.shelf != ArchiveShelf.operational_library:
        raise ArchiveWorkflowError("Only an Operational Library item can be proposed for transfer")
    item.shelf = ArchiveShelf.transfer
    item.status = ArchiveItemStatus.approved
    item.target_room = target_room
    await db.flush()
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="archive.item.propose_transfer",
        room=item.room,
        entity_type="archive_item",
        entity_id=item.id,
        after={"target_room": target_room.value},
    )
    return item


async def deliver(db: AsyncSession, item_id: str, *, actor_type: ActorType = ActorType.system, actor_id: str | None = None) -> ArchiveItem:
    """Moves a transfer-shelf item onto the target room's receiving shelf.
    The item's `room` field flips to the target — this is the transfer."""
    item = await _require_item(db, item_id)
    if item.shelf != ArchiveShelf.transfer or item.target_room is None:
        raise ArchiveWorkflowError("Item is not staged for transfer")
    source_room = item.room
    item.source_room = source_room
    item.room = item.target_room
    item.target_room = None
    item.shelf = ArchiveShelf.receiving
    item.status = ArchiveItemStatus.received
    await db.flush()
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="archive.item.deliver",
        room=item.room,
        entity_type="archive_item",
        entity_id=item.id,
        before={"source_room": source_room.value},
        after={"received_by_room": item.room.value},
    )
    return item


async def review(db: AsyncSession, item_id: str, reviewed_by: str) -> ArchiveItem:
    item = await _require_item(db, item_id)
    if item.shelf != ArchiveShelf.receiving or item.status != ArchiveItemStatus.received:
        raise ArchiveWorkflowError("Item is not awaiting review")
    item.status = ArchiveItemStatus.reviewed
    item.reviewed_by = reviewed_by
    item.reviewed_at = utcnow()
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=reviewed_by,
        action="archive.item.review",
        room=item.room,
        entity_type="archive_item",
        entity_id=item.id,
    )
    return item


async def accept(db: AsyncSession, item_id: str, reviewed_by: str) -> ArchiveItem:
    """Promotes a reviewed Receiving-shelf item into the room's own
    Operational Library — the only way an item becomes the room's
    working truth. Never automatic."""
    item = await _require_item(db, item_id)
    if item.shelf != ArchiveShelf.receiving or item.status != ArchiveItemStatus.reviewed:
        raise ArchiveWorkflowError("Item must be reviewed before it can be accepted")
    item.shelf = ArchiveShelf.operational_library
    item.status = ArchiveItemStatus.active
    item.version += 1
    item.reviewed_by = reviewed_by
    item.reviewed_at = utcnow()
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=reviewed_by,
        action="archive.item.accept",
        room=item.room,
        entity_type="archive_item",
        entity_id=item.id,
        after={"version": item.version},
    )
    return item


async def reject(db: AsyncSession, item_id: str, reviewed_by: str) -> ArchiveItem:
    item = await _require_item(db, item_id)
    if item.shelf != ArchiveShelf.receiving:
        raise ArchiveWorkflowError("Only a Receiving-shelf item can be rejected")
    item.status = ArchiveItemStatus.rejected
    item.reviewed_by = reviewed_by
    item.reviewed_at = utcnow()
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=reviewed_by,
        action="archive.item.reject",
        room=item.room,
        entity_type="archive_item",
        entity_id=item.id,
    )
    return item


async def _require_item(db: AsyncSession, item_id: str) -> ArchiveItem:
    item = await db.get(ArchiveItem, item_id)
    if item is None:
        raise ArchiveWorkflowError("Archive item not found")
    return item
