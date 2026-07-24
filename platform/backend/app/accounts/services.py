"""Task 1 business logic. Registry secret reveal is the one operation in
this whole codebase that decrypts a credential — it is separately
permissioned at the router layer (`accounts:reveal_secret`) and always
audit-logged here, and its return value must never be handed to a
provider/LLM call.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import (
    AccountRegistryEntry,
    ApiHealthStatus,
    ApiMonitorEntry,
    FinancialRecord,
)
from app.core.models.audit import ActorType
from app.core.models.common import RoomName, utcnow
from app.core.models.ledger import LedgerEntry, LedgerEntryType
from app.core.security.encryption import decrypt_secret, encrypt_secret
from app.core.services import audit_service, spend_service


# --- Account Registry ---

async def create_registry_entry(db: AsyncSession, *, staff_id: str, secret: str | None, **fields) -> AccountRegistryEntry:
    entry = AccountRegistryEntry(
        created_by=staff_id,
        secret_ciphertext=encrypt_secret(secret) if secret else None,
        **fields,
    )
    db.add(entry)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.registry.create",
        room=RoomName.accounts,
        entity_type="account_registry_entry",
        entity_id=entry.id,
        after={"name": entry.name, "category": entry.category.value},
    )
    return entry


async def update_registry_entry(db: AsyncSession, entry_id: str, *, staff_id: str, secret: str | None = None, **fields) -> AccountRegistryEntry | None:
    entry = await db.get(AccountRegistryEntry, entry_id)
    if entry is None:
        return None
    before = {"name": entry.name, "renewal_date": str(entry.renewal_date)}
    for key, value in fields.items():
        if value is not None:
            setattr(entry, key, value)
    if secret is not None:
        entry.secret_ciphertext = encrypt_secret(secret)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.registry.update",
        room=RoomName.accounts,
        entity_type="account_registry_entry",
        entity_id=entry.id,
        before=before,
        after={"name": entry.name, "renewal_date": str(entry.renewal_date)},
    )
    return entry


async def list_registry_entries(db: AsyncSession) -> list[AccountRegistryEntry]:
    result = await db.execute(select(AccountRegistryEntry).order_by(AccountRegistryEntry.name))
    return list(result.scalars().all())


async def reveal_secret(db: AsyncSession, entry_id: str, *, staff_id: str, ip_address: str | None) -> str | None:
    """Decrypts and returns a registry secret. This is the single choke
    point for secret access — always audit-logged, regardless of outcome."""
    entry = await db.get(AccountRegistryEntry, entry_id)
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.registry.reveal_secret",
        room=RoomName.accounts,
        entity_type="account_registry_entry",
        entity_id=entry_id,
        note="Secret value is not itself logged.",
        ip_address=ip_address,
    )
    if entry is None or entry.secret_ciphertext is None:
        return None
    return decrypt_secret(entry.secret_ciphertext)


# --- Financial Record ---

async def create_financial_record(db: AsyncSession, *, staff_id: str, **fields) -> FinancialRecord:
    record = FinancialRecord(created_by=staff_id, **fields)
    db.add(record)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.financial_record.create",
        room=RoomName.accounts,
        entity_type="financial_record",
        entity_id=record.id,
        after={"description": record.description, "amount": str(record.amount)},
    )
    return record


async def list_financial_records(db: AsyncSession) -> list[FinancialRecord]:
    result = await db.execute(select(FinancialRecord).order_by(FinancialRecord.incurred_at.desc()))
    return list(result.scalars().all())


async def financial_summary(db: AsyncSession) -> dict:
    records = await list_financial_records(db)
    total_manual = sum((r.amount for r in records), Decimal("0"))
    by_category: dict[str, Decimal] = {}
    for r in records:
        by_category[r.category.value] = by_category.get(r.category.value, Decimal("0")) + r.amount

    result = await db.execute(
        select(LedgerEntry).where(LedgerEntry.entry_type == LedgerEntryType.agent_spend)
    )
    agent_entries = list(result.scalars().all())
    total_agent_spend = -sum((e.amount for e in agent_entries), Decimal("0"))  # spend rows are stored negative

    room_summaries = []
    for room in (RoomName.accounts, RoomName.profiles, RoomName.meeting_room):
        room_summaries.append(await spend_service.get_room_summary(db, room))

    return {
        "total_manual_expenses": total_manual,
        "total_agent_spend": total_agent_spend,
        "by_category": by_category,
        "room_summaries": room_summaries,
    }


async def financial_record_timeseries(
    db: AsyncSession, *, since: date | None = None, bucket: Literal["day", "week"] = "day"
) -> list[dict]:
    """Manual expenses (hosting, tools, subscriptions, ...) over time,
    grouped by category — the non-LLM half of the admin Accounts-Room
    landing dashboard's "system costs over a timeline, per service"
    chart (`core.llm_usage_service.get_usage_timeseries` is the other
    half, for LLM token spend specifically)."""
    period = func.date_trunc(bucket, FinancialRecord.incurred_at).label("period")
    stmt = (
        select(
            period,
            FinancialRecord.category,
            func.coalesce(func.sum(FinancialRecord.amount), 0).label("total_amount"),
        )
        .group_by(period, FinancialRecord.category)
        .order_by(period)
    )
    if since is not None:
        stmt = stmt.where(FinancialRecord.incurred_at >= since)
    result = await db.execute(stmt)
    return [
        {"period": row.period, "category": row.category.value, "total_amount": row.total_amount}
        for row in result.all()
    ]


# --- API Monitor ---

async def create_api_monitor_entry(db: AsyncSession, *, staff_id: str, **fields) -> ApiMonitorEntry:
    entry = ApiMonitorEntry(last_checked_at=utcnow(), **fields)
    db.add(entry)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.api_monitor.create",
        room=RoomName.accounts,
        entity_type="api_monitor_entry",
        entity_id=entry.id,
        after={"service_name": entry.service_name},
    )
    return entry


async def update_api_monitor_entry(db: AsyncSession, entry_id: str, *, staff_id: str, **fields) -> ApiMonitorEntry | None:
    entry = await db.get(ApiMonitorEntry, entry_id)
    if entry is None:
        return None
    before = {k: str(getattr(entry, k)) for k in fields}
    for key, value in fields.items():
        if value is not None:
            setattr(entry, key, value)
    entry.last_checked_at = utcnow()
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.api_monitor.update",
        room=RoomName.accounts,
        entity_type="api_monitor_entry",
        entity_id=entry_id,
        before=before,
        after={k: str(v) for k, v in fields.items()},
    )
    return entry


async def list_api_monitor_entries(db: AsyncSession) -> list[ApiMonitorEntry]:
    result = await db.execute(select(ApiMonitorEntry).order_by(ApiMonitorEntry.service_name))
    return list(result.scalars().all())


async def services_needing_attention(db: AsyncSession) -> list[ApiMonitorEntry]:
    entries = await list_api_monitor_entries(db)
    return [
        e
        for e in entries
        if e.health_status in (ApiHealthStatus.degraded, ApiHealthStatus.down)
        or (e.credit_remaining is not None and e.monthly_limit and e.credit_remaining < e.monthly_limit * Decimal("0.1"))
    ]


# --- Administrative agent (reads broadly, cannot touch protected settings) ---

async def administrative_summary(db: AsyncSession) -> dict:
    from app.core.services import calendar_service

    upcoming = await calendar_service.list_for_room(db, RoomName.accounts)
    soon_cutoff = utcnow() + timedelta(days=30)
    upcoming_renewals = [e for e in upcoming if e.due_at <= soon_cutoff]

    attention = await services_needing_attention(db)
    summary = await financial_summary(db)

    return {
        "upcoming_renewals": upcoming_renewals,
        "services_needing_attention": attention,
        "financial_summary": summary,
    }
