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

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow
from app.core.models.ledger import LedgerEntry, LedgerEntryType
from app.core.services import audit_service, scope_service
from app.profiles.models import (
    ConsentContext,
    ConsentRecord,
    Identity,
    IdentityType,
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
    staff_id: str,
) -> Identity:
    parent: Identity | None = None
    if parent_id is not None:
        parent = await db.get(Identity, parent_id)
        if parent is None:
            raise ProfilesError("Parent identity not found")
        if parent.id_type == IdentityType.member:
            raise ProfilesError("A Member ID is a leaf and cannot have children")
    elif id_type == IdentityType.member:
        raise ProfilesError("A root identity must be a Group ID")

    identity = Identity(name=name, id_type=id_type, parent_id=parent_id, path="", created_by=staff_id)
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
        actor_type=ActorType.staff,
        actor_id=staff_id,
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
