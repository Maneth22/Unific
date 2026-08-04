"""Raw inbound/outbound webhook traffic, logged unconditionally — the
ground truth for "what did the provider actually send/receive," kept
separate from `AuditLog` (which records actions taken, not raw wire
payloads) and from `meeting_room.Message` (which only exists once a
payload has been successfully parsed into a normalized message). A
malformed or rejected payload still gets a row here, which is the whole
point: it is what makes debugging real Meta traffic possible without
SSH-ing into the server to read logs.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import RoomName, utcnow, uuid_str
from app.database import Base


class WebhookDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class WebhookLog(Base):
    __tablename__ = "webhook_log"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[WebhookDirection] = mapped_column(Enum(WebhookDirection, name="webhook_direction"), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
