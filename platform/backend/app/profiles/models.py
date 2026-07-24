"""Task 2 — the ID registry. `identity` is a self-referencing tree
(Group -> Group -> ... -> Member, arbitrary depth); `path` is a
materialized path (dot-joined ancestor ids) used for O(log n) ancestor/
descendant scope checks via a prefix-indexed lookup — see
`app.core.services.scope_service`.

Note on the materialized path implementation: the approved plan called
for Postgres `ltree` + GiST index. `ltree`'s wire format isn't one
asyncpg decodes without a custom type codec registered per-connection,
which is real operational complexity for a single-tenant pilot's ID
tree (expected to be dozens-to-low-hundreds of rows, not millions). A
plain indexed materialized-path column gives the same O(log n)
index-range-scan characteristics for prefix (ancestor/descendant)
queries without that integration risk — same guarantee, lower risk.
Swapping to real `ltree` later is a migration, not a redesign, since
`scope_service` is the only place that reads `path` directly.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class IdentityType(str, enum.Enum):
    group = "group"
    member = "member"


class Identity(Base):
    """A node in the registry tree. A `member` is always a leaf — enforced
    in `services.py`, not the database, since it depends on the sibling
    rows at creation time.

    `created_by`/`created_by_client_id` are best-effort, mutually
    exclusive convenience columns (mirroring the pattern already used by
    `meeting_room.SessionReport.generated_by_staff_id`/
    `generated_by_client_id`) recording which kind of actor created this
    node — a staff member (manual provisioning, or approving a client
    registration), a client (creating a community group under their own
    scope), or neither (a member created via public self-registration,
    `actor_type=system`, both columns null). The audit log
    (`app.core.services.audit_service`) is the actual source of truth for
    "who did this"; these columns just make the common case fast to read
    without joining audit_log."""

    __tablename__ = "identity"
    __table_args__ = (
        Index("ix_identity_path_pattern", "path", postgresql_ops={"path": "text_pattern_ops"}),
        {"schema": "profiles"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.identity.id", ondelete="RESTRICT"), nullable=True, index=True)
    id_type: Mapped[IdentityType] = mapped_column(Enum(IdentityType, name="identity_type"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_by_client_id: Mapped[str | None] = mapped_column(ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    permission: Mapped["Permission"] = relationship(back_populates="identity", uselist=False, cascade="all, delete-orphan")
    profile_account: Mapped["ProfileAccount"] = relationship(back_populates="identity", uselist=False, cascade="all, delete-orphan")
    member_profile: Mapped["MemberProfile"] = relationship(back_populates="identity", uselist=False, cascade="all, delete-orphan")
    client_org_profile: Mapped["ClientOrgProfile"] = relationship(back_populates="identity", uselist=False, cascade="all, delete-orphan")
    ilc_group_profile: Mapped["IlcGroupProfile"] = relationship(back_populates="identity", uselist=False, cascade="all, delete-orphan")


class PermissionScope(str, enum.Enum):
    none = "none"
    within_tree = "within_tree"
    any = "any"


_SCOPE_RANK = {PermissionScope.none: 0, PermissionScope.within_tree: 1, PermissionScope.any: 2}


class Permission(Base):
    """One row per identity. `own_*` is this identity's explicit
    override (null = inherit); `effective_*` is precomputed by
    `app.core.services.permission_cascade` and is what every read path
    (including the WhatsApp message gate) actually uses — never
    recomputed live on the hot path.
    """

    __tablename__ = "permission"
    __table_args__ = {"schema": "profiles"}

    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), primary_key=True)

    own_registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    own_connected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    own_auto_respond: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    own_send_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    own_can_message_scope: Mapped[PermissionScope | None] = mapped_column(Enum(PermissionScope, name="permission_scope"), nullable=True)
    own_can_receive_scope: Mapped[PermissionScope | None] = mapped_column(Enum(PermissionScope, name="permission_scope"), nullable=True)
    own_credit_cap: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)

    own_reply_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    own_reply_tone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    own_reply_complexity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    own_reply_character: Mapped[str | None] = mapped_column(String(100), nullable=True)
    own_reply_language: Mapped[str | None] = mapped_column(String(20), nullable=True)

    consent_required: Mapped[bool] = mapped_column(Boolean, nullable=False)

    effective_registered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_auto_respond: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_send_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_can_message_scope: Mapped[PermissionScope] = mapped_column(
        Enum(PermissionScope, name="permission_scope"), nullable=False, default=PermissionScope.within_tree
    )
    effective_can_receive_scope: Mapped[PermissionScope] = mapped_column(
        Enum(PermissionScope, name="permission_scope"), nullable=False, default=PermissionScope.within_tree
    )
    effective_credit_cap: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    effective_reply_role: Mapped[str] = mapped_column(String(100), nullable=False, default="member")
    effective_reply_tone: Mapped[str] = mapped_column(String(100), nullable=False, default="friendly")
    effective_reply_complexity: Mapped[str] = mapped_column(String(100), nullable=False, default="standard")
    effective_reply_character: Mapped[str] = mapped_column(String(100), nullable=False, default="assistant")
    effective_reply_language: Mapped[str] = mapped_column(String(20), nullable=False, default="en")

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    identity: Mapped["Identity"] = relationship(back_populates="permission")


class ProfileAccount(Base):
    """One token-credit account per identity. Funding/spend always write
    a `core.ledger_entry` in the same transaction — see
    `app.core.services.gate_service` / `funding_service`."""

    __tablename__ = "profile_account"
    __table_args__ = {"schema": "profiles"}

    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    identity: Mapped["Identity"] = relationship(back_populates="profile_account")


class ConsentContext(str, enum.Enum):
    onboarding = "onboarding"
    record_time = "record_time"


class ConsentRecord(Base):
    __tablename__ = "consent_record"
    __table_args__ = {"schema": "profiles"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True)
    context: Mapped[ConsentContext] = mapped_column(Enum(ConsentContext, name="consent_context"), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retention_period: Mapped[str] = mapped_column(String(100), default="")
    data_residency: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    captured_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class GroupInvite(Base):
    """A public registration link for one Group identity (a client's
    community, e.g. "Sandahkal Group India"). At most one row may be
    `is_active` per `identity_id` (enforced by the partial unique index
    below) — regenerating an invite deactivates the current row and
    inserts a new one rather than mutating the token in place, so a
    leaked old link goes cold instead of silently being reused, and the
    full history of every token ever issued for a community is kept.

    The public registration flow (`app.profiles.router`'s unauthenticated
    `public_router`) reads a `GroupInvite` by `token` to find which group
    a submitted member-registration form belongs to."""

    __tablename__ = "group_invite"
    __table_args__ = (
        Index("uq_group_invite_active_identity", "identity_id", unique=True, postgresql_where=text("is_active")),
        {"schema": "profiles"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_client_id: Mapped[str | None] = mapped_column(ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True)
    created_by_staff_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class MemberProfile(Base):
    """One row per Member identity created via the public registration
    form — the descriptive info the form collects (name lives on
    `Identity.name` itself; this holds the rest). Deliberately duplicates
    `phone_number` with `meeting_room.WhatsAppLink`: that table is the
    operational routing record the message pipeline actually reads,
    this one is the descriptive record the client dashboard reads — same
    "no cross-schema back-reference" style already used elsewhere between
    these two rooms.

    `extra_info` (not `metadata` — that name collides with SQLAlchemy's
    `Base.metadata`) holds whatever additional fields the registration
    form collected beyond name/email/phone."""

    __tablename__ = "member_profile"
    __table_args__ = {"schema": "profiles"}

    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    extra_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    registered_via: Mapped[str] = mapped_column(String(50), default="public_form")
    source_invite_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.group_invite.id", ondelete="SET NULL"), nullable=True)
    # Which pre-issued IlcMemberRoster row this member's registration
    # number was verified against — set at registration, never reassigned.
    ilc_roster_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.ilc_member_roster.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    identity: Mapped["Identity"] = relationship(back_populates="member_profile")


class GroupCodeSequence(Base):
    """Backs the system-issued, human-readable "Group ID" shown on client
    orgs and ILC groups (e.g. `CLI-000001`, `ILC-000001`) — one row per
    prefix, incremented atomically (`UPDATE ... SET next_value = next_value
    + 1 RETURNING next_value`, see `services._generate_group_code`) so
    concurrent creates never collide, unlike a `COUNT(*) + 1` scheme."""

    __tablename__ = "group_code_sequence"
    __table_args__ = {"schema": "profiles"}

    prefix: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ClientOrgProfile(Base):
    """The client-organization-only fields, 1:1 with the org's root
    `Identity` — kept as real typed columns (not `extra_info` JSONB) since
    the shape is fixed and known, matching `MemberProfile`'s pattern of a
    dedicated profile table per identity "kind" rather than overloading
    `Identity` itself with kind-specific columns."""

    __tablename__ = "client_org_profile"
    __table_args__ = {"schema": "profiles"}

    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), primary_key=True)
    group_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(255), default="")
    role_description: Mapped[str] = mapped_column(Text, default="")
    abn_acnc_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    identity: Mapped["Identity"] = relationship(back_populates="client_org_profile")


class IlcGroupProfile(Base):
    """The ILC-community-group-only fields, 1:1 with the group's
    `Identity` — same "dedicated profile table" pattern as
    `ClientOrgProfile`/`MemberProfile`. `Identity.name` already holds
    "Name (English)"; `name_hindi` here is the other half of the
    bilingual-name requirement."""

    __tablename__ = "ilc_group_profile"
    __table_args__ = {"schema": "profiles"}

    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), primary_key=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    identity: Mapped["Identity"] = relationship(back_populates="ilc_group_profile")


class IlcMemberRoster(Base):
    """A client-assigned, pre-issued ILC registration number for one
    community group — the allow-list the public member-registration form
    checks against (see `services.create_member_profile`): unrecognized
    numbers are rejected outright, and a number already claimed by an
    existing member is rejected as a duplicate. Uniqueness is scoped per
    group (`(group_identity_id, ilc_registration_number)`), not global —
    two different ILC groups may reuse the same number, matching how
    separate cooperative registrations are actually numbered."""

    __tablename__ = "ilc_member_roster"
    __table_args__ = (
        Index(
            "uq_ilc_member_roster_group_number",
            "group_identity_id",
            "ilc_registration_number",
            unique=True,
        ),
        {"schema": "profiles"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    group_identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True)
    ilc_registration_number: Mapped[str] = mapped_column(String(64), nullable=False)
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    claimed_by_identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="SET NULL"), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_client_id: Mapped[str | None] = mapped_column(ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
