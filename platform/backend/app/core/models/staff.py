"""Staff identity and access — the UNIFIC master-dashboard side.

Client identity (`client_user`) is defined in `app.profiles.models` once
the identity tree exists, since a client user is meaningless without an
`identity_id` to scope to (see Phase C).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import RoomName, RoomPermission, utcnow, uuid_str
from app.database import Base


class StaffUser(Base):
    """A UNIFIC staff account. Access to any given room is not implied by
    this row alone — it is granted explicitly per room via
    `StaffRoomAccess` (least privilege by default, per the Flags doc)."""

    __tablename__ = "staff_user"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Reserved for future TOTP-based MFA on staff accounts touching Task 1
    # (the "crown jewels" module) — not enforced yet, field present so the
    # login flow doesn't need reshaping later.
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Eager (selectin) load: StaffOut always serializes room_access, and
    # doing that lazily inside a Pydantic validator after the session's
    # async context has moved on is exactly the MissingGreenlet trap —
    # load it as part of the same query instead of patching every call site.
    room_access: Mapped[list["StaffRoomAccess"]] = relationship(
        back_populates="staff_user",
        foreign_keys="StaffRoomAccess.staff_user_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class StaffRoomAccess(Base):
    """One row per (staff, room) grant. A staff member may hold 1-8 of
    these — the master-dashboard permission model described in the docs."""

    __tablename__ = "staff_room_access"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    staff_user_id: Mapped[str] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False)
    permission: Mapped[RoomPermission] = mapped_column(
        Enum(RoomPermission, name="room_permission"), default=RoomPermission.read, nullable=False
    )
    granted_by: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    staff_user: Mapped["StaffUser"] = relationship(
        back_populates="room_access", foreign_keys=[staff_user_id]
    )

    __table_args__ = (
        Index("ix_staff_room_access_user_room", "staff_user_id", "room", unique=True),
        {"schema": "core"},
    )


class RefreshToken(Base):
    """A rotating, revocable refresh token. One row per issued token;
    `revoked_at` set on logout, rotation, or reuse detection. Belongs to
    either a staff user or a client user (exactly one), so this table is
    shared across both login flows rather than duplicated per audience."""

    __tablename__ = "refresh_token"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    staff_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String, nullable=True)


class LoginAttempt(Base):
    """Failed/successful login attempts, keyed by the login identifier
    (email) — used for rate limiting and temporary lockout."""

    __tablename__ = "login_attempt"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
