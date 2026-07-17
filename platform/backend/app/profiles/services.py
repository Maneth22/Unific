"""Task 2 business logic: the identity tree, the permission-narrowing
cascade, profile-account funding/trickle-down, and consent.

The cascade is the load-bearing piece: every `effective_*` value is
computed here — parent-first — and stored, so the hot path (a WhatsApp
message arriving in Phase D) reads O(1) instead of walking ancestors
live. Narrowing is self-enforcing by construction (AND for booleans,
MIN for numeric/ranked scopes) rather than validated-and-rejected, so
even a bad write can't produce an effective value wider than the parent
allows.
"""
from __future__ import annotations

import secrets
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.client import ClientRegistrationRequest, ClientRegistrationStatus, ClientUser
from app.core.models.common import RoomName, utcnow
from app.core.models.ledger import LedgerEntry, LedgerEntryType
from app.core.security.password import hash_password
from app.core.services import audit_service, scope_service
from app.profiles.models import (
    ConsentContext,
    ConsentRecord,
    GroupInvite,
    Identity,
    IdentityType,
    MemberProfile,
    Permission,
    PermissionScope,
    ProfileAccount,
    _SCOPE_RANK,
)


class ProfilesError(Exception):
    pass


ROOT_DEFAULTS = {
    "registered": True,
    "connected": False,
    "auto_respond": False,
    "send_on": True,
    "can_message_scope": PermissionScope.within_tree,
    "can_receive_scope": PermissionScope.within_tree,
    "reply_role": "member",
    "reply_tone": "friendly",
    "reply_complexity": "standard",
    "reply_character": "assistant",
    "reply_language": "en",
}


def _merge_bool(own: bool | None, parent_eff: bool | None, is_root: bool, default: bool) -> bool:
    if is_root:
        return own if own is not None else default
    return parent_eff if own is None else (own and parent_eff)


def _merge_scope(own: PermissionScope | None, parent_eff: PermissionScope | None, is_root: bool, default: PermissionScope) -> PermissionScope:
    if is_root:
        return own if own is not None else default
    if own is None:
        return parent_eff
    return own if _SCOPE_RANK[own] <= _SCOPE_RANK[parent_eff] else parent_eff


def _merge_credit_cap(own: Decimal | None, parent_eff: Decimal | None, is_root: bool) -> Decimal | None:
    if is_root:
        return own
    if own is None:
        return parent_eff
    if parent_eff is None:
        return own
    return min(own, parent_eff)


def _merge_config(own: str | None, parent_eff: str | None, is_root: bool, default: str) -> str:
    if own is not None:
        return own
    return parent_eff if not is_root else default


def _compute_effective(perm: Permission, parent_perm: Permission | None) -> None:
    """Mutates `perm.effective_*` in place from `perm.own_*` and the
    parent's already-computed `effective_*` (or ROOT_DEFAULTS if none)."""
    is_root = parent_perm is None
    p = parent_perm

    perm.effective_registered = _merge_bool(perm.own_registered, p.effective_registered if p else None, is_root, ROOT_DEFAULTS["registered"])
    perm.effective_connected = _merge_bool(perm.own_connected, p.effective_connected if p else None, is_root, ROOT_DEFAULTS["connected"])
    perm.effective_auto_respond = _merge_bool(perm.own_auto_respond, p.effective_auto_respond if p else None, is_root, ROOT_DEFAULTS["auto_respond"])
    perm.effective_send_on = _merge_bool(perm.own_send_on, p.effective_send_on if p else None, is_root, ROOT_DEFAULTS["send_on"])

    perm.effective_can_message_scope = _merge_scope(
        perm.own_can_message_scope, p.effective_can_message_scope if p else None, is_root, ROOT_DEFAULTS["can_message_scope"]
    )
    perm.effective_can_receive_scope = _merge_scope(
        perm.own_can_receive_scope, p.effective_can_receive_scope if p else None, is_root, ROOT_DEFAULTS["can_receive_scope"]
    )

    perm.effective_credit_cap = _merge_credit_cap(perm.own_credit_cap, p.effective_credit_cap if p else None, is_root)

    perm.effective_reply_role = _merge_config(perm.own_reply_role, p.effective_reply_role if p else None, is_root, ROOT_DEFAULTS["reply_role"])
    perm.effective_reply_tone = _merge_config(perm.own_reply_tone, p.effective_reply_tone if p else None, is_root, ROOT_DEFAULTS["reply_tone"])
    perm.effective_reply_complexity = _merge_config(
        perm.own_reply_complexity, p.effective_reply_complexity if p else None, is_root, ROOT_DEFAULTS["reply_complexity"]
    )
    perm.effective_reply_character = _merge_config(
        perm.own_reply_character, p.effective_reply_character if p else None, is_root, ROOT_DEFAULTS["reply_character"]
    )
    perm.effective_reply_language = _merge_config(
        perm.own_reply_language, p.effective_reply_language if p else None, is_root, ROOT_DEFAULTS["reply_language"]
    )


async def recompute_cascade(db: AsyncSession, identity_id: str) -> None:
    """Recomputes effective permissions for `identity_id` and every
    descendant, parent-first, in a single pass — called after any own_*
    change or a subtree move."""
    ids = await scope_service.descendant_ids(db, identity_id, include_self=True)
    for node_id in ids:
        identity = await db.get(Identity, node_id)
        perm = await db.get(Permission, node_id)
        parent_perm = await db.get(Permission, identity.parent_id) if identity.parent_id else None
        _compute_effective(perm, parent_perm)
    await db.flush()


# --- Identity tree ---

async def create_identity(
    db: AsyncSession,
    *,
    name: str,
    id_type: IdentityType,
    parent_id: str | None,
    actor_type: ActorType,
    actor_id: str | None,
) -> Identity:
    """The one identity-creation path, used by staff creating any node,
    clients creating a community Group under their own scope, and the
    public member-registration endpoint (`actor_type=system`, `actor_id
    =None`) creating a Member. `actor_type` decides which creator column
    gets stamped — see `Identity`'s docstring."""
    parent: Identity | None = None
    if parent_id is not None:
        parent = await db.get(Identity, parent_id)
        if parent is None:
            raise ProfilesError("Parent identity not found")
        if parent.id_type == IdentityType.member:
            raise ProfilesError("A Member ID is a leaf and cannot have children")
    elif id_type == IdentityType.member:
        raise ProfilesError("A root identity must be a Group ID")

    identity = Identity(
        name=name,
        id_type=id_type,
        parent_id=parent_id,
        path="",
        created_by=actor_id if actor_type == ActorType.staff else None,
        created_by_client_id=actor_id if actor_type == ActorType.client else None,
    )
    db.add(identity)
    await db.flush()  # assigns identity.id
    identity.path = scope_service.child_path(parent.path if parent else None, identity.id)

    parent_perm = await db.get(Permission, parent_id) if parent_id else None
    perm = Permission(identity_id=identity.id, consent_required=(id_type == IdentityType.member))
    _compute_effective(perm, parent_perm)
    db.add(perm)

    db.add(ProfileAccount(identity_id=identity.id))

    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="profiles.identity.create",
        room=RoomName.profiles,
        entity_type="identity",
        entity_id=identity.id,
        after={"name": name, "id_type": id_type.value, "parent_id": parent_id},
    )
    return identity


async def list_tree(db: AsyncSession) -> list[Identity]:
    result = await db.execute(select(Identity).order_by(Identity.path))
    return list(result.scalars().all())


async def get_identity(db: AsyncSession, identity_id: str) -> Identity | None:
    return await db.get(Identity, identity_id)


async def update_own_permission(
    db: AsyncSession, identity_id: str, *, actor_type: ActorType, actor_id: str | None, **own_fields
) -> Permission:
    perm = await db.get(Permission, identity_id)
    if perm is None:
        raise ProfilesError("Identity not found")
    before = {k: getattr(perm, k) for k in own_fields}
    for key, value in own_fields.items():
        setattr(perm, key, value)
    await db.flush()
    await recompute_cascade(db, identity_id)

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="profiles.permission.update",
        room=RoomName.profiles,
        entity_type="permission",
        entity_id=identity_id,
        before=before,
        after=own_fields,
    )
    return perm


async def move_subtree(db: AsyncSession, identity_id: str, new_parent_id: str, staff_id: str) -> Identity:
    identity = await db.get(Identity, identity_id)
    new_parent = await db.get(Identity, new_parent_id)
    if identity is None or new_parent is None:
        raise ProfilesError("Identity not found")
    if new_parent.id_type == IdentityType.member:
        raise ProfilesError("Cannot move a subtree under a Member ID")
    if await scope_service.is_ancestor_or_self(db, root_id=identity_id, target_id=new_parent_id):
        raise ProfilesError("Cannot move a subtree under its own descendant")

    await scope_service.reparent_subtree(db, identity_id, new_parent.path)
    identity.parent_id = new_parent_id
    await db.flush()
    await recompute_cascade(db, identity_id)

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="profiles.identity.move",
        room=RoomName.profiles,
        entity_type="identity",
        entity_id=identity_id,
        after={"new_parent_id": new_parent_id},
    )
    return identity


# --- Profile accounts (funding, trickle-down) ---

async def fund_identity(
    db: AsyncSession,
    identity_id: str,
    amount: Decimal,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    description: str = "",
) -> ProfileAccount:
    if amount <= 0:
        raise ProfilesError("Funding amount must be positive")
    account = await db.get(ProfileAccount, identity_id)
    if account is None:
        raise ProfilesError("Identity not found")
    account.balance += amount
    account.updated_at = utcnow()

    audit = await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="profiles.account.fund",
        room=RoomName.profiles,
        entity_type="profile_account",
        entity_id=identity_id,
        after={"amount": str(amount)},
    )
    db.add(
        LedgerEntry(
            entry_type=LedgerEntryType.funding,
            room=RoomName.profiles,
            identity_id=identity_id,
            amount=amount,
            balance_after=account.balance,
            description=description,
            audit_log_id=audit.id,
        )
    )
    await db.flush()
    return account


async def transfer_credit(
    db: AsyncSession,
    from_identity_id: str,
    to_identity_id: str,
    amount: Decimal,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    description: str = "",
) -> None:
    """Trickles credit from a group to a descendant — the only direction
    the docs describe ("money trickles down group -> group and
    group -> member")."""
    if amount <= 0:
        raise ProfilesError("Transfer amount must be positive")
    if not await scope_service.is_ancestor_or_self(db, root_id=from_identity_id, target_id=to_identity_id):
        raise ProfilesError("Credit can only trickle down to a descendant identity")

    from_account = await db.get(ProfileAccount, from_identity_id)
    to_account = await db.get(ProfileAccount, to_identity_id)
    if from_account is None or to_account is None:
        raise ProfilesError("Identity not found")
    if from_account.balance < amount:
        raise ProfilesError("Insufficient balance to transfer")

    to_perm = await db.get(Permission, to_identity_id)
    if to_perm.effective_credit_cap is not None and to_account.balance + amount > to_perm.effective_credit_cap:
        raise ProfilesError("Transfer would exceed the recipient's credit cap")

    from_account.balance -= amount
    to_account.balance += amount
    from_account.updated_at = utcnow()
    to_account.updated_at = utcnow()

    audit = await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="profiles.account.transfer",
        room=RoomName.profiles,
        entity_type="profile_account",
        entity_id=to_identity_id,
        after={"from": from_identity_id, "to": to_identity_id, "amount": str(amount)},
    )
    db.add_all(
        [
            LedgerEntry(
                entry_type=LedgerEntryType.customer_transfer,
                room=RoomName.profiles,
                identity_id=from_identity_id,
                amount=-amount,
                balance_after=from_account.balance,
                description=description or f"Transfer to {to_identity_id}",
                audit_log_id=audit.id,
            ),
            LedgerEntry(
                entry_type=LedgerEntryType.customer_transfer,
                room=RoomName.profiles,
                identity_id=to_identity_id,
                amount=amount,
                balance_after=to_account.balance,
                description=description or f"Transfer from {from_identity_id}",
                audit_log_id=audit.id,
            ),
        ]
    )
    await db.flush()


# --- Consent ---

async def record_consent(
    db: AsyncSession,
    identity_id: str,
    *,
    context: ConsentContext,
    granted: bool,
    staff_id: str | None,
    retention_period: str = "",
    data_residency: str = "",
    note: str = "",
) -> ConsentRecord:
    record = ConsentRecord(
        identity_id=identity_id,
        context=context,
        granted=granted,
        retention_period=retention_period,
        data_residency=data_residency,
        note=note,
        captured_by=staff_id,
    )
    db.add(record)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff if staff_id else ActorType.system,
        actor_id=staff_id,
        action="profiles.consent.record",
        room=RoomName.profiles,
        entity_type="consent_record",
        entity_id=record.id,
        after={"identity_id": identity_id, "context": context.value, "granted": granted},
    )
    return record


async def list_consent(db: AsyncSession, identity_id: str) -> list[ConsentRecord]:
    result = await db.execute(
        select(ConsentRecord).where(ConsentRecord.identity_id == identity_id).order_by(ConsentRecord.granted_at.desc())
    )
    return list(result.scalars().all())


# --- Community groups & registration invites ---

async def create_or_rotate_group_invite(
    db: AsyncSession, *, identity_id: str, actor_type: ActorType, actor_id: str | None
) -> GroupInvite:
    """Deactivates any current active invite for this group and inserts a
    fresh one — regenerate-not-mutate, so a leaked old link goes cold and
    the full history of tokens ever issued survives."""
    identity = await db.get(Identity, identity_id)
    if identity is None:
        raise ProfilesError("Identity not found")
    if identity.id_type != IdentityType.group:
        raise ProfilesError("Only a Group identity can have a registration invite")

    current = await get_active_invite(db, identity_id)
    if current is not None:
        current.is_active = False
        await db.flush()

    invite = GroupInvite(
        identity_id=identity_id,
        token=secrets.token_urlsafe(24),
        created_by_client_id=actor_id if actor_type == ActorType.client else None,
        created_by_staff_id=actor_id if actor_type == ActorType.staff else None,
    )
    db.add(invite)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="profiles.group_invite.create",
        room=RoomName.profiles,
        entity_type="group_invite",
        entity_id=invite.id,
        after={"identity_id": identity_id},
    )
    return invite


async def get_active_invite(db: AsyncSession, identity_id: str) -> GroupInvite | None:
    result = await db.execute(
        select(GroupInvite).where(GroupInvite.identity_id == identity_id, GroupInvite.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_invite_by_token(db: AsyncSession, token: str) -> GroupInvite | None:
    result = await db.execute(select(GroupInvite).where(GroupInvite.token == token, GroupInvite.is_active.is_(True)))
    invite = result.scalar_one_or_none()
    if invite is None:
        return None
    identity = await db.get(Identity, invite.identity_id)
    if identity is None or not identity.is_active:
        return None
    return invite


async def create_member_profile(
    db: AsyncSession,
    *,
    identity_id: str,
    email: str,
    phone_number: str,
    extra_info: dict,
    source_invite_id: str | None,
) -> MemberProfile:
    profile = MemberProfile(
        identity_id=identity_id,
        email=email,
        phone_number=phone_number,
        extra_info=extra_info,
        registered_via="public_form",
        source_invite_id=source_invite_id,
    )
    db.add(profile)
    await db.flush()
    return profile


async def get_member_profile(db: AsyncSession, identity_id: str) -> MemberProfile | None:
    return await db.get(MemberProfile, identity_id)


async def list_members(db: AsyncSession, group_id: str) -> list[Identity]:
    """A group's members are always its direct children (a Member is
    always a leaf, created directly under the group it registered into),
    so this is a parent_id filter, not a descendant-tree walk."""
    result = await db.execute(
        select(Identity)
        .where(Identity.parent_id == group_id, Identity.id_type == IdentityType.member)
        .order_by(Identity.created_at)
    )
    return list(result.scalars().all())


async def list_client_groups(db: AsyncSession, client_identity_id: str) -> list[Identity]:
    """The client's own community groups — every Group identity in their
    subtree, excluding their own root (that's "your organization", not a
    community they created)."""
    ids = await scope_service.descendant_ids(db, client_identity_id, include_self=False)
    if not ids:
        return []
    result = await db.execute(
        select(Identity)
        .where(Identity.id.in_(ids), Identity.id_type == IdentityType.group)
        .order_by(Identity.path)
    )
    return list(result.scalars().all())


# --- Client self-registration & admin approval ---

async def submit_client_registration(
    db: AsyncSession, *, org_name: str, contact_name: str, email: str, password: str
) -> ClientRegistrationRequest:
    normalized_email = email.lower()

    existing_user = await db.execute(select(ClientUser).where(ClientUser.email == normalized_email))
    if existing_user.scalar_one_or_none() is not None:
        raise ProfilesError("Email already registered")

    existing_pending = await db.execute(
        select(ClientRegistrationRequest).where(
            ClientRegistrationRequest.email == normalized_email,
            ClientRegistrationRequest.status == ClientRegistrationStatus.pending,
        )
    )
    if existing_pending.scalar_one_or_none() is not None:
        raise ProfilesError("A registration request for this email is already pending")

    request = ClientRegistrationRequest(
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
        action="profiles.client_registration.submit",
        room=RoomName.profiles,
        entity_type="client_registration_request",
        entity_id=request.id,
        after={"org_name": org_name, "email": normalized_email},
    )
    return request


async def list_registration_requests(
    db: AsyncSession, *, status: ClientRegistrationStatus | None = None
) -> list[ClientRegistrationRequest]:
    query = select(ClientRegistrationRequest).order_by(ClientRegistrationRequest.created_at.desc())
    if status is not None:
        query = query.where(ClientRegistrationRequest.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())


async def approve_client_registration(db: AsyncSession, request_id: str, *, actor_id: str) -> ClientUser:
    request = await db.get(ClientRegistrationRequest, request_id)
    if request is None:
        raise ProfilesError("Registration request not found")
    if request.status != ClientRegistrationStatus.pending:
        raise ProfilesError(f"Request is already {request.status.value}")

    existing_user = await db.execute(select(ClientUser).where(ClientUser.email == request.email))
    if existing_user.scalar_one_or_none() is not None:
        raise ProfilesError("Email already registered")

    root_group = await create_identity(
        db,
        name=request.org_name,
        id_type=IdentityType.group,
        parent_id=None,
        actor_type=ActorType.staff,
        actor_id=actor_id,
    )

    client = ClientUser(
        email=request.email,
        password_hash=request.password_hash,
        full_name=request.contact_name,
        identity_id=root_group.id,
    )
    db.add(client)
    await db.flush()

    request.status = ClientRegistrationStatus.approved
    request.reviewed_by = actor_id
    request.reviewed_at = utcnow()
    request.created_client_user_id = client.id
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=actor_id,
        action="profiles.client_registration.approve",
        room=RoomName.profiles,
        entity_type="client_registration_request",
        entity_id=request.id,
        after={"client_user_id": client.id, "identity_id": root_group.id},
    )
    return client


async def reject_client_registration(
    db: AsyncSession, request_id: str, *, actor_id: str, reason: str = ""
) -> ClientRegistrationRequest:
    request = await db.get(ClientRegistrationRequest, request_id)
    if request is None:
        raise ProfilesError("Registration request not found")
    if request.status != ClientRegistrationStatus.pending:
        raise ProfilesError(f"Request is already {request.status.value}")

    request.status = ClientRegistrationStatus.rejected
    request.rejection_reason = reason
    request.reviewed_by = actor_id
    request.reviewed_at = utcnow()
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=actor_id,
        action="profiles.client_registration.reject",
        room=RoomName.profiles,
        entity_type="client_registration_request",
        entity_id=request.id,
        after={"reason": reason},
    )
    return request
