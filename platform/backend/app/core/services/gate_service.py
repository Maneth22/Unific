"""The gate: the single choke point any paid action must pass through
before it runs. Everything up to and including a Meeting Room reply
drawn from the room's own Shelf 1 is UNIFIC's free-to-near-free running
cost (tracked via `spend_service` against the room's own account, not
the member's) — this function is what a future Task 4-8 paid action
will call to charge an identity's own balance instead, and what already
enforces "must be registered" on every message today, at cost=0.

Lives in `core` (not `profiles`) because it is explicitly cross-room:
Task 3 (and later 4-8) call it against Task 2's identity/permission/
account data — see the Plan-agent review this was built against.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow
from app.core.models.ledger import LedgerEntry, LedgerEntryType
from app.core.services import audit_service
from app.profiles.models import Permission, ProfileAccount


class GateError(Exception):
    pass


async def check_and_charge(
    db: AsyncSession,
    *,
    identity_id: str,
    room: RoomName,
    action: str,
    cost: Decimal = Decimal("0"),
    require_connected: bool = False,
    actor_type: ActorType = ActorType.system,
    actor_id: str | None = None,
) -> None:
    perm = await db.get(Permission, identity_id)
    account = await db.get(ProfileAccount, identity_id)
    if perm is None or account is None:
        raise GateError("Identity not found")

    if not perm.effective_registered:
        raise GateError("Identity is not registered")
    if require_connected and not perm.effective_connected:
        raise GateError("Identity is not connected to this room")

    if cost <= 0:
        return  # free action — reads, ledger maths, formatting cost nothing to run

    if account.balance < cost:
        raise GateError("Insufficient balance for this action")

    account.balance -= cost
    account.updated_at = utcnow()

    audit = await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action=f"gate.charge.{action}",
        room=room,
        entity_type="profile_account",
        entity_id=identity_id,
        after={"cost": str(cost), "action": action},
    )
    db.add(
        LedgerEntry(
            entry_type=LedgerEntryType.gate_charge,
            room=room,
            identity_id=identity_id,
            amount=-cost,
            balance_after=account.balance,
            description=action,
            audit_log_id=audit.id,
        )
    )
    await db.flush()
