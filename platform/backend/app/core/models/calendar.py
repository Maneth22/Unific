"""The one master calendar (Task 1's Calendar Engine). Every room submits
its own timing rows here rather than keeping a private calendar — Task 2
submits token-refill/permission-expiry/consent windows, Task 3 submits
meeting schedules and reply windows, and so on for future rooms. The
Calendar agent is event-driven: reads/writes/triggers are free, so this
model carries no cost fields.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import RoomName, utcnow, uuid_str
from app.database import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_event"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    reminder_fired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
