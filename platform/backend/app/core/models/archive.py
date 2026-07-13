"""The three-shelf Archive Locker pattern, shared by every room.

A room's "locker" is not a separate table — it is simply the set of
`ArchiveItem` rows tagged with that room. Shelf 1 (Operational Library) is
the room's permanent working truth; agents read directly from it. Shelf 2
(Transfer) is a staging area for material approved to leave the room.
Shelf 3 (Receiving) holds material delivered from another room, pending
review — it is never auto-accepted into Shelf 1.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import RoomName, utcnow, uuid_str
from app.database import Base


class ArchiveShelf(str, enum.Enum):
    operational_library = "operational_library"
    transfer = "transfer"
    receiving = "receiving"


class ArchiveItemStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"       # approved for transfer out (shelf 2)
    received = "received"       # arrived on shelf 3, not yet looked at
    reviewed = "reviewed"       # looked at, decision pending
    accepted = "accepted"       # promoted into the receiving room's shelf 1
    rejected = "rejected"
    active = "active"           # normal, live shelf-1 item


class ArchiveItem(Base):
    __tablename__ = "archive_item"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False, index=True)
    shelf: Mapped[ArchiveShelf] = mapped_column(Enum(ArchiveShelf, name="archive_shelf"), nullable=False, index=True)
    status: Mapped[ArchiveItemStatus] = mapped_column(
        Enum(ArchiveItemStatus, name="archive_item_status"), default=ArchiveItemStatus.active, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    item_type: Mapped[str] = mapped_column(String(100), default="document")
    content: Mapped[dict] = mapped_column(JSONB, default=dict)
    # For an item on a Receiving shelf: which room sent it.
    source_room: Mapped[RoomName | None] = mapped_column(Enum(RoomName, name="room_name"), nullable=True)
    # For an item approved for outbound transfer: which room it is bound for.
    target_room: Mapped[RoomName | None] = mapped_column(Enum(RoomName, name="room_name"), nullable=True)
    # Content the Meeting Room's auto-reply mode is allowed to draw from —
    # only ever true for accepted/active Operational Library items.
    approved_for_auto_reply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
