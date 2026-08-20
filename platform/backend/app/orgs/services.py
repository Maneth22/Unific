"""`orgs` schema business logic: org self-registration + admin approval,
org-user provisioning, groups, group invites, and member self-registration
(the public redemption flow `app.orgs.models.GroupInvite`'s docstring
deferred to Prompt 3 — now built, see `register_member` below).

Every mutating function takes `actor_type`/`actor_id` as keyword-only
args (never hardcoded) and calls `audit_service.record` — mirrors
`app.profiles.services`'s discipline exactly. Functions flush, never
commit — the caller (router) commits, so a whole request is one
transaction.
"""
from __future__ import annotations

import secrets

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow
from app.core.security.password import hash_password
from app.core.services import audit_service
from app.orgs.models import (
    Group,
    GroupInvite,
    Member,
    Org,
    OrgRegistrationRequest,
    OrgRegistrationStatus,
    OrgUser,
    OrgUserRole,
)


class OrgsError(Exception):
    pass


async def _generate_org_code(db: AsyncSession, prefix: str) -> str:
    """Atomically increments the shared per-prefix sequence (a single
    UPSERT, not read-then-write) and returns e.g. "ORG-000042" — race-
    safe under concurrent creates. Mirrors
    `app.profiles.services._generate_group_code` exactly, against
    `orgs.code_sequence` instead of `profiles.group_code_sequence`."""
    result = await db.execute(
        text(
            "INSERT INTO orgs.code_sequence (prefix, next_value) VALUES (:prefix, 1) "
            "ON CONFLICT (prefix) DO UPDATE SET next_value = orgs.code_sequence.next_value + 1 "
            "RETURNING next_value"
        ),
        {"prefix": prefix},
    )
    next_value = result.scalar_one()
    return f"{prefix}-{next_value:06d}"


# --- Org self-registration & admin approval --------------------------------


async def submit_org_registration(
    db: AsyncSession, *, org_name: str, contact_name: str, email: str, password: str
) -> OrgRegistrationRequest:
    """Mirrors `app.profiles.services.submit_client_registration` exactly,
    targeting `OrgRegistrationRequest`/`OrgUser` instead of
    `ClientRegistrationRequest`/`ClientUser`."""
    normalized_email = email.lower()

    existing_user = await db.execute(select(OrgUser).where(OrgUser.email == normalized_email))
    if existing_user.scalar_one_or_none() is not None:
        raise OrgsError("Email already registered")

    existing_pending = await db.execute(
        select(OrgRegistrationRequest).where(
            OrgRegistrationRequest.email == normalized_email,
            OrgRegistrationRequest.status == OrgRegistrationStatus.pending,
        )
    )
    if existing_pending.scalar_one_or_none() is not None:
        raise OrgsError("A registration request for this email is already pending")

    request = OrgRegistrationRequest(
        org_name=org_name,
        contact_name=contact_name,
        email=normalized_email,
        password_hash=hash_password(password),
    )
    db.add(request)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.system,
        actor_id=None,
        action="orgs.registration.submit",
        room=RoomName.orgs,
        entity_type="org_registration_request",
        entity_id=request.id,
        after={"org_name": org_name, "email": normalized_email},
    )
    return request


async def list_org_registration_requests(
    db: AsyncSession, *, status: OrgRegistrationStatus | None = None
) -> list[OrgRegistrationRequest]:
    query = select(OrgRegistrationRequest).order_by(OrgRegistrationRequest.created_at.desc())
    if status is not None:
        query = query.where(OrgRegistrationRequest.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())


async def approve_org_registration(db: AsyncSession, request_id: str, *, actor_id: str) -> OrgUser:
    """Mirrors `app.profiles.services.approve_client_registration`'s exact
    transaction-boundary pattern: creates `Org` directly (no separate
    identity+profile — `Org` *is* the org row now) + `OrgUser(role=owner)`
    bound to it, stamps the request, audits, single transaction (caller
    commits)."""
    request = await db.get(OrgRegistrationRequest, request_id)
    if request is None:
        raise OrgsError("Registration request not found")
    if request.status != OrgRegistrationStatus.pending:
        raise OrgsError(f"Request is already {request.status.value}")

    existing_user = await db.execute(select(OrgUser).where(OrgUser.email == request.email))
    if existing_user.scalar_one_or_none() is not None:
        raise OrgsError("Email already registered")

    group_code = await _generate_org_code(db, "ORG")
    org = Org(name=request.org_name, group_code=group_code)
    db.add(org)
    await db.flush()

    owner = OrgUser(
        org_id=org.id,
        email=request.email,
        password_hash=request.password_hash,
        full_name=request.contact_name,
        role=OrgUserRole.owner,
        created_by_staff_id=actor_id,
    )
    db.add(owner)
    await db.flush()

    request.status = OrgRegistrationStatus.approved
    request.reviewed_by = actor_id
    request.reviewed_at = utcnow()
    request.created_org_id = org.id
    request.created_org_user_id = owner.id
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=actor_id,
        action="orgs.registration.approve",
        room=RoomName.orgs,
        entity_type="org_registration_request",
        entity_id=request.id,
        after={"org_id": org.id, "org_user_id": owner.id},
    )
    return owner


async def reject_org_registration(
    db: AsyncSession, request_id: str, *, actor_id: str, reason: str = ""
) -> OrgRegistrationRequest:
    request = await db.get(OrgRegistrationRequest, request_id)
    if request is None:
        raise OrgsError("Registration request not found")
    if request.status != OrgRegistrationStatus.pending:
        raise OrgsError(f"Request is already {request.status.value}")

    request.status = OrgRegistrationStatus.rejected
    request.rejection_reason = reason
    request.reviewed_by = actor_id
    request.reviewed_at = utcnow()
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=actor_id,
        action="orgs.registration.reject",
        room=RoomName.orgs,
        entity_type="org_registration_request",
        entity_id=request.id,
        note=reason,
    )
    return request


# --- Org-user provisioning ---------------------------------------------


async def create_org_user(
    db: AsyncSession,
    *,
    org_id: str,
    email: str,
    password: str,
    full_name: str,
    role: OrgUserRole,
    actor_type: ActorType,
    actor_id: str | None,
) -> OrgUser:
    """An owner provisioning a co-owner/staff account under their own
    org."""
    normalized_email = email.lower()
    existing = await db.execute(select(OrgUser).where(OrgUser.email == normalized_email))
    if existing.scalar_one_or_none() is not None:
        raise OrgsError("Email already registered")

    org_user = OrgUser(
        org_id=org_id,
        email=normalized_email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        created_by_org_user_id=actor_id if actor_type == ActorType.org_user else None,
        created_by_staff_id=actor_id if actor_type == ActorType.staff else None,
    )
    db.add(org_user)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="orgs.org_user.create",
        room=RoomName.orgs,
        entity_type="org_user",
        entity_id=org_user.id,
        after={"email": normalized_email, "role": role.value},
    )
    return org_user


# --- Groups --------------------------------------------------------------


async def create_group(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    actor_type: ActorType,
    actor_id: str | None,
    **ilc_fields,
) -> Group:
    group_code = await _generate_org_code(db, "GRP")
    group = Group(org_id=org_id, name=name, group_code=group_code, **ilc_fields)
    db.add(group)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="orgs.group.create",
        room=RoomName.orgs,
        entity_type="group",
        entity_id=group.id,
        after={"org_id": org_id, "name": name},
    )
    return group


async def update_group(
    db: AsyncSession, group_id: str, *, actor_type: ActorType, actor_id: str | None, **fields
) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise OrgsError("Group not found")

    before = {key: getattr(group, key) for key in fields}
    for key, value in fields.items():
        setattr(group, key, value)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="orgs.group.update",
        room=RoomName.orgs,
        entity_type="group",
        entity_id=group.id,
        before=before,
        after=fields,
    )
    return group


# --- Group invites ---------------------------------------------------------


async def create_group_invite(
    db: AsyncSession,
    *,
    org_id: str,
    group_id: str | None,
    actor_type: ActorType,
    actor_id: str | None,
) -> GroupInvite:
    """Deactivates any existing active invite for the same `(org_id,
    group_id)` pair first, then inserts a new row — regenerate, not
    mutate, mirrors `profiles.GroupInvite`'s pattern so full history is
    retained."""
    existing = await db.execute(
        select(GroupInvite).where(
            GroupInvite.org_id == org_id,
            GroupInvite.group_id == group_id,
            GroupInvite.is_active.is_(True),
        )
    )
    for row in existing.scalars().all():
        row.is_active = False

    invite = GroupInvite(
        org_id=org_id,
        group_id=group_id,
        token=secrets.token_urlsafe(24),
        created_by_org_user_id=actor_id if actor_type == ActorType.org_user else None,
        created_by_staff_id=actor_id if actor_type == ActorType.staff else None,
    )
    db.add(invite)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="orgs.group_invite.create",
        room=RoomName.orgs,
        entity_type="group_invite",
        entity_id=invite.id,
        after={"org_id": org_id, "group_id": group_id},
    )
    return invite


async def get_invite_by_token(db: AsyncSession, token: str) -> GroupInvite | None:
    """Mirrors `app.profiles.services.get_invite_by_token` exactly. No
    roster-number allow-list check exists here (unlike the legacy
    `IlcMemberRoster` gate) — flagged as an open question in
    docs/PHASE_2_NOTES.md for whether that concept comes back later."""
    result = await db.execute(select(GroupInvite).where(GroupInvite.token == token, GroupInvite.is_active.is_(True)))
    invite = result.scalar_one_or_none()
    if invite is None:
        return None
    org = await db.get(Org, invite.org_id)
    if org is None or not org.is_active:
        return None
    return invite


async def register_member(
    db: AsyncSession, *, org_id: str, group_id: str | None, name: str, actor_type: ActorType, actor_id: str | None
) -> Member:
    """Public self-registration entry point — creates a `Member` directly
    under `org_id` (and `group_id`, if the redeemed invite was
    group-scoped). Instant, no review, per the rebuild directive. Unlike
    the legacy `register_member`, there is no pre-instructed-member
    ("client_added") reconciliation step — every redemption creates a
    fresh row; flagged as an open question if that workflow is needed
    later."""
    member = Member(org_id=org_id, group_id=group_id, name=name)
    db.add(member)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="orgs.member.register",
        room=RoomName.orgs,
        entity_type="member",
        entity_id=member.id,
        after={"org_id": org_id, "group_id": group_id, "name": name},
    )
    return member
