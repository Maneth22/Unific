"""Staff identity and access — the UNIFIC master-dashboard side.

Client identity (`client_user`) is defined in `app.profiles.models` once
the identity tree exists, since a client user is meaningless without an
`identity_id` to scope to (see Phase C).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class StaffUser(Base):
    """A UNIFIC staff account — every staff row is a full Admin. There is
    no per-room grant model: any active staff account can read/write every
    room, and can provision another staff account (see `app.core.security.
    dependencies.require_admin`). The previous per-room `StaffRoomAccess`
    grant table and `is_superadmin` distinction were collapsed into this
    single role by deliberate choice, not by accident."""

    __tablename__ = "staff_user"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Reserved for future TOTP-based MFA on staff accounts touching Task 1
    # (the "crown jewels" module) — not enforced yet, field present so the
    # login flow doesn't need reshaping later.
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


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
