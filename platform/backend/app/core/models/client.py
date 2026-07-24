"""Client (group-ID) login — the narrower counterpart to `StaffUser`.
Lives in `core` alongside `StaffUser` since both share the refresh-token
table and login-attempt machinery, but a client is always scoped to
exactly one `profiles.identity` row (their root) plus its descendants —
see `app.profiles.security.require_identity_scope`.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class ClientUser(Base):
    """A full-access, org-scoped login — either the original org-owner
    account (created via `approve_client_registration`) or a co-owner
    provisioned later by a platform Admin (`is_owner=True` either way;
    the flag is a display/audit label, not a privilege distinction —
    every `ClientUser` row has identical access to its org). Distinct
    from `ClientStaffUser` below, which is deliberately narrower."""

    __tablename__ = "client_user"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_owner: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ClientStaffUser(Base):
    """A limited, org-scoped login a `ClientUser` (org owner/co-owner)
    creates for their own employees. Mirrors `ClientUser`'s shape but is a
    separate table, not a role flag on it — it needs its own JWT audience
    (`"client_staff"`, alongside `"staff"`/`"client"`) so route-gating is a
    type check (can this token even decode as `audience="client"`?), not a
    role check baked into token claims. Full read/write on ILC groups,
    members, and meetings under the org (reuses `require_identity_scope`
    as-is — scope is purely tree-position, agnostic to owner-vs-staff);
    blocked from money (accounts-overview, funding, transfer) and from
    managing other client-staff/co-owner logins — see
    `app.profiles.security.require_client_owner`."""

    __tablename__ = "client_staff_user"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_client_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ClientRegistrationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ClientRegistrationRequest(Base):
    """A pending client (organisation) signup, staged here rather than as
    a half-formed `ClientUser` row. `ClientUser.identity_id` is NOT NULL
    and read as non-optional everywhere (`require_identity_scope`, every
    client route) — a signup has no identity yet, so it can't become a
    real `ClientUser` until an Admin approves it. Approval
    (`app.profiles.services.approve_client_registration`) atomically
    creates the root Group `Identity` (named `org_name`) and the real
    `ClientUser` bound to it, then stamps this row `approved` and links
    `created_client_user_id`.

    No DB-level unique constraint on `email`: a rejected org may resubmit
    with the same address. The service layer checks for an existing
    active `ClientUser` or a currently-`pending` request with that email
    before inserting, mirroring the 409-on-duplicate pattern already used
    by `create_client_account`."""

    __tablename__ = "client_registration_request"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ClientRegistrationStatus] = mapped_column(
        Enum(ClientRegistrationStatus, name="client_registration_status"),
        default=ClientRegistrationStatus.pending,
        nullable=False,
    )
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_client_user_id: Mapped[str | None] = mapped_column(ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
