"""Staff identity and access — the UNIFIC master-dashboard side.

Client identity (`client_user`) is defined in `app.profiles.models` once
the identity tree exists, since a client user is meaningless without an
`identity_id` to scope to (see Phase C).
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class StaffTier(str, enum.Enum):
    """The only access-relevant field on `StaffUser`. `admin` sees and can
    manage everything (clients, staff, cost/API data, meeting scheduling —
    every existing `require_admin`-gated route). `staff` is deliberately
    narrow: their own assigned tasks, their own progress/concern updates,
    and their own inbox — never client data, cost dashboards, or another
    staff member's tasks unless an admin routes a message to them."""

    admin = "admin"
    staff = "staff"


class StaffCategory(Base):
    """An admin-managed label for grouping staff-tier accounts (e.g.
    "Developer", "Marketing") — purely organizational, carries no access
    implications of its own. A `staff`-tier account without a category is
    legal (just unusual); enforcing "staff must have one" is a service-
    layer rule, not a DB constraint, matching how this codebase already
    puts business rules like "a Member is a leaf" in services rather than
    the schema."""

    __tablename__ = "staff_category"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class StaffUser(Base):
    """A UNIFIC staff account. `tier` is the only access-relevant field —
    `admin` gets every existing `require_admin`-gated route; `staff` is
    restricted to their own tasks/updates/inbox (see `app.tasking` and
    `app.core.security.dependencies.require_admin` / `require_any_staff`).
    This reverses the previous "every staff row is a full Admin" collapse
    by deliberate choice, per a later requirement that regular staff get a
    narrower, task-focused interface rather than full system access."""

    __tablename__ = "staff_user"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[StaffTier] = mapped_column(Enum(StaffTier, name="staff_tier"), nullable=False, default=StaffTier.staff)
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_category.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    exactly one of a staff user, a client (org-owner) user, or a client-
    staff user, so this table is shared across all three login flows
    rather than duplicated per audience."""

    __tablename__ = "refresh_token"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    staff_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    client_staff_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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
