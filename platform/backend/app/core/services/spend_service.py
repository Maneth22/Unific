"""Every room's account, and every agent's sub-account within it — the
"room contract" piece that makes spend traceable to the agent that
incurred it. This tracks UNIFIC's own operating cost (Task 1's Financial
Dashboard / Token Management), distinct from the customer-facing token
gate in `app.profiles`/Phase C, which spends from an identity's own
`profile_account` balance instead.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName, utcnow
from app.core.models.ledger import LedgerEntry, LedgerEntryType
from app.core.models.room_account import AgentSubAccount, RoomAccount


async def ensure_room_account(db: AsyncSession, room: RoomName) -> RoomAccount:
    result = await db.execute(select(RoomAccount).where(RoomAccount.room == room))
    account = result.scalar_one_or_none()
    if account is None:
        account = RoomAccount(room=room)
        db.add(account)
        await db.flush()
    return account


async def ensure_agent_sub_account(db: AsyncSession, room: RoomName, agent_name: str) -> AgentSubAccount:
    room_account = await ensure_room_account(db, room)
    result = await db.execute(
        select(AgentSubAccount).where(
            AgentSubAccount.room_account_id == room_account.id,
            AgentSubAccount.agent_name == agent_name,
        )
    )
    sub_account = result.scalar_one_or_none()
    if sub_account is None:
        sub_account = AgentSubAccount(room_account_id=room_account.id, agent_name=agent_name)
        db.add(sub_account)
        await db.flush()
    return sub_account


async def fund_room_account(
    db: AsyncSession, room: RoomName, amount: Decimal, description: str = "", audit_log_id: str | None = None
) -> RoomAccount:
    account = await ensure_room_account(db, room)
    account.balance += amount
    account.updated_at = utcnow()
    db.add(
        LedgerEntry(
            entry_type=LedgerEntryType.funding,
            room=room,
            amount=amount,
            balance_after=account.balance,
            description=description,
            audit_log_id=audit_log_id,
        )
    )
    await db.flush()
    return account


async def record_spend(
    db: AsyncSession,
    *,
    room: RoomName,
    agent_name: str,
    amount: Decimal,
    description: str = "",
    audit_log_id: str | None = None,
) -> AgentSubAccount:
    """Records what an agent spent. Task 1's base service is UNIFIC-funded
    (free-to-near-free up to the Meeting Room gate), so this deliberately
    does not block on insufficient balance — it is a transparency ledger,
    not the customer-facing gate. Going negative here is itself the
    financial-dashboard signal that a room is running over budget.
    """
    sub_account = await ensure_agent_sub_account(db, room, agent_name)
    room_account = await ensure_room_account(db, room)

    sub_account.balance -= amount
    room_account.balance -= amount
    sub_account.updated_at = utcnow()
    room_account.updated_at = utcnow()

    db.add(
        LedgerEntry(
            entry_type=LedgerEntryType.agent_spend,
            room=room,
            agent_name=agent_name,
            amount=-amount,
            balance_after=sub_account.balance,
            description=description,
            audit_log_id=audit_log_id,
        )
    )
    await db.flush()
    return sub_account


async def get_room_summary(db: AsyncSession, room: RoomName) -> dict:
    room_account = await ensure_room_account(db, room)
    result = await db.execute(
        select(AgentSubAccount).where(AgentSubAccount.room_account_id == room_account.id)
    )
    sub_accounts = list(result.scalars().all())
    return {
        "room": room.value,
        "balance": room_account.balance,
        "agents": [{"agent_name": a.agent_name, "balance": a.balance} for a in sub_accounts],
    }
