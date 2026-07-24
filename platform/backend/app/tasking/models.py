"""Internal staff task-tracking and inbox — the "common interface" regular
(non-admin) staff use: their assigned tasks, progress/concern updates, and
messages to/from the admin or other staff. Tagged `RoomName.initial_tasking`
(reserved but unused until now) for audit/ledger consistency with every
other room's business data.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    cancelled = "cancelled"


class Task(Base):
    """Assigned by an admin (`assigned_by_staff_id`) to a staff account
    (`assigned_to_staff_id`) — enforcing "assigner must be tier=admin" is a
    service-layer rule, not a DB constraint, matching this codebase's
    existing style for business rules like "a Member is a leaf"."""

    __tablename__ = "task"
    __table_args__ = {"schema": "tasking"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    assigned_by_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_staff_id: Mapped[str] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), default=TaskStatus.open, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    updates: Mapped[list["TaskUpdate"]] = relationship(back_populates="task", cascade="all, delete-orphan", order_by="TaskUpdate.created_at")


class TaskUpdate(Base):
    """Append-only progress log for a task — mirrors `ConsentRecord`'s/
    `AuditLog`'s insert-only pattern, never edited or deleted, so "latest
    update" is just the newest row. `is_concern` is the flag a staff
    member raises for the admin's attention (surfaced on the admin
    dashboard's "open concerns" view)."""

    __tablename__ = "task_update"
    __table_args__ = {"schema": "tasking"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasking.task.id", ondelete="CASCADE"), nullable=False, index=True)
    author_staff_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    progress_status: Mapped[TaskStatus | None] = mapped_column(Enum(TaskStatus, name="task_status"), nullable=True)
    is_concern: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    task: Mapped["Task"] = relationship(back_populates="updates")


class InboxMessage(Base):
    """One polymorphic inbox, reused for staff<->admin, staff<->staff, and
    client<->admin notices — the same XOR-actor idiom `meeting_room.
    MeetingParticipant` already established (there, one of identity_id/
    staff_user_id; here, doubled for sender AND recipient, each
    independently either a staff row or a client row)."""

    __tablename__ = "inbox_message"
    __table_args__ = (
        CheckConstraint(
            "(sender_staff_id IS NOT NULL) != (sender_client_id IS NOT NULL)",
            name="one_sender",
        ),
        CheckConstraint(
            "(recipient_staff_id IS NOT NULL) != (recipient_client_id IS NOT NULL)",
            name="one_recipient",
        ),
        Index("ix_inbox_message_recipient_staff_unread", "recipient_staff_id", "read_at"),
        Index("ix_inbox_message_recipient_client_unread", "recipient_client_id", "read_at"),
        {"schema": "tasking"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    sender_staff_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    sender_client_id: Mapped[str | None] = mapped_column(ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True)
    recipient_staff_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=True)
    recipient_client_id: Mapped[str | None] = mapped_column(ForeignKey("core.client_user.id", ondelete="CASCADE"), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    related_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasking.task.id", ondelete="SET NULL"), nullable=True)
    related_meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meeting_room.meeting.id", ondelete="SET NULL"), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
