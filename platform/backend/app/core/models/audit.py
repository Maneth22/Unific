"""The append-only audit log — every mutating action across every room
writes here. Distinct from `LedgerEntry` (financial movements only):
this table covers *all* actions (logins, permission changes, secret
reveals, sends), financial or not, per the Token/Ledger note that keeps
these as separate layers with a clean link, not a merge.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import RoomName, utcnow, uuid_str
from app.database import Base


class ActorType(str, enum.Enum):
    staff = "staff"
    client = "client"
    system = "system"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    room: Mapped[RoomName | None] = mapped_column(Enum(RoomName, name="room_name"), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
