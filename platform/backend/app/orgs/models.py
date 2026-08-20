"""The `orgs` schema — a flat replacement for the old `accounts`+`profiles`
identity tree + cascading permission model (see docs/adr/0003). `Org` and
`OrgUser` replace `ClientUser`/`ClientStaffUser` (merged into one table
with a `role` enum instead of two audience-typed tables); `Group` is the
one allowed level of sub-grouping (`Org -> Group -> Member`, max depth 3,
no recursion) and folds in the old `IlcGroupProfile`'s fields directly,
since it's no longer a separate 1:1-with-an-Identity profile table.

This schema is additive alongside the untouched `app.profiles`/
`app.accounts` — nothing here repoints an existing FK. `Member` is
deliberately minimal: phone/email/registration fields land in Prompt 3
(member self-registration via `group_invite` is that phase's job), this
table only needs to exist now so Prompt 3 is an additive column
migration, not a new table.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class OrgRegistrationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class OrgUserRole(str, enum.Enum):
    owner = "owner"
    staff = "staff"


class Org(Base):
    """An organization is a first-class row now, not implied by an
    identity-tree root — folds in the old `ClientOrgProfile`'s fields
    directly."""

    __tablename__ = "org"
    __table_args__ = {"schema": "orgs"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(255), default="")
    role_description: Mapped[str] = mapped_column(Text, default="")
    abn_acnc_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A simple denormalized running total, not a per-group/per-member
    # balance like the old profiles.ProfileAccount (one row per identity
    # in the tree). Per-group/per-member balances are an open question
    # for whichever later phase builds spend-gating against this schema
    # — see docs/PHASE_1_NOTES.md.
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Group(Base):
    """The one allowed level of sub-grouping under an Org (see module
    docstring) — folds in the old `IlcGroupProfile`'s fields directly
    since there's no separate Identity for it to be a 1:1 profile of
    anymore; `Group` itself carries them."""

    __tablename__ = "group"
    __table_args__ = {"schema": "orgs"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name_hindi: Mapped[str] = mapped_column(String(255), default="")
    registration_number: Mapped[str] = mapped_column(String(100), default="")
    date_of_registration: Mapped[date | None] = mapped_column(Date, nullable=True)
    application_signed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registered_office: Mapped[str] = mapped_column(Text, default="")
    area_of_operation: Mapped[str] = mapped_column(Text, default="")
    governing_act: Mapped[str] = mapped_column(String(255), default="")
    registering_authority: Mapped[str] = mapped_column(String(255), default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    cooperative_type: Mapped[str] = mapped_column(String(255), default="")
    bank_account: Mapped[str] = mapped_column(String(100), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class OrgUser(Base):
    """Client-side login — replaces `ClientUser`/`ClientStaffUser`'s two
    audience-typed tables with one table + a `role` enum. Unlike the
    legacy split (where owner-vs-staff was enforced purely by which
    audience a token decoded against), `role` here is a real column a
    dependency must actually check — see `app.orgs.security.
    require_org_owner`."""

    __tablename__ = "org_user"
    __table_args__ = {"schema": "orgs"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[OrgUserRole] = mapped_column(Enum(OrgUserRole, name="org_user_role"), nullable=False)
    created_by_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
    created_by_org_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("orgs.org_user.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Member(Base):
    """Deliberately minimal for Prompt 2 — see module docstring."""

    __tablename__ = "member"
    __table_args__ = {"schema": "orgs"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    # Denormalized (also reachable via group_id -> Group.org_id) so scope
    # checks are a single equality comparison, never a join — see
    # app.orgs.security's flat-scope helper.
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("orgs.group.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class OrgRegistrationRequest(Base):
    """A pending org signup, staged — mirrors
    `core.ClientRegistrationRequest` exactly, targeting `Org`/`OrgUser`
    instead of `Identity`/`ClientUser`."""

    __tablename__ = "org_registration_request"
    __table_args__ = {"schema": "orgs"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # No DB-level unique constraint — a rejected org may resubmit; dedup
    # against a *pending* request is enforced in the service layer.
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[OrgRegistrationStatus] = mapped_column(
        Enum(OrgRegistrationStatus, name="org_registration_status"),
        nullable=False,
        default=OrgRegistrationStatus.pending,
    )
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_org_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.org.id", ondelete="SET NULL"), nullable=True)
    created_org_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("orgs.org_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class GroupInvite(Base):
    """A public registration link for one Group (or, with `group_id`
    null, for direct org membership). Table + a basic "org owner/staff
    creates an invite" endpoint only in Prompt 2 — public redemption
    (creates a `Member` + phone link + wa.me redirect) is Prompt 3's job.
    """

    __tablename__ = "group_invite"
    __table_args__ = (
        Index(
            "uq_group_invite_active_org_group",
            "org_id",
            "group_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        {"schema": "orgs"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.group.id", ondelete="CASCADE"), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_org_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("orgs.org_user.id", ondelete="SET NULL"), nullable=True
    )
    created_by_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class OrgCodeSequence(Base):
    """Atomic-UPSERT increment for human-readable codes (e.g.
    "ORG-000001"), mirroring `profiles.GroupCodeSequence`'s pattern —
    kept as its own table so `orgs` has zero table-level coupling to
    `profiles`."""

    __tablename__ = "code_sequence"
    __table_args__ = {"schema": "orgs"}

    prefix: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_value: Mapped[int] = mapped_column(nullable=False, default=1)
