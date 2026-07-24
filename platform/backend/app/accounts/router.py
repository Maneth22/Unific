"""Task 1 — Accounts room API. Every route depends on `require_admin` —
the server-side boundary; nothing here trusts the frontend to have hidden
a nav item. There is no per-room grant model any more (see
`app.core.security.dependencies`), so `reveal_secret` below — previously
the one route requiring the stricter `RoomPermission.admin` tier — now
only requires "is an active staff member," same as every other route in
this router. That is an intentional consequence of collapsing staff roles
to a single Admin role, not an oversight.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import schemas, services
from app.accounts.models import AccountCategory, ApiHealthStatus, FinancialRecordCategory
from app.core.models.archive import ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.common import RoomName
from app.core.models.staff import StaffUser
from app.core.security.dependencies import client_ip, require_admin
from app.core.services import archive_service, calendar_service, llm_usage_service
from app.database import get_db

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

admin = require_admin


# --- Account Registry ---

@router.get("/registry", response_model=list[schemas.AccountRegistryOut])
async def list_registry(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    entries = await services.list_registry_entries(db)
    return [_to_registry_out(e) for e in entries]


@router.post("/registry", response_model=schemas.AccountRegistryOut, status_code=status.HTTP_201_CREATED)
async def create_registry(
    req: schemas.AccountRegistryCreate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        category = AccountCategory(req.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid category: {req.category}") from exc

    entry = await services.create_registry_entry(
        db,
        staff_id=staff.id,
        secret=req.secret,
        name=req.name,
        category=category,
        provider=req.provider,
        purpose=req.purpose,
        owner=req.owner,
        renewal_date=req.renewal_date,
        linked_api=req.linked_api,
        documentation_url=req.documentation_url,
    )
    await db.commit()
    return _to_registry_out(entry)


@router.put("/registry/{entry_id}", response_model=schemas.AccountRegistryOut)
async def update_registry(
    entry_id: str,
    req: schemas.AccountRegistryUpdate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    fields = req.model_dump(exclude={"secret"}, exclude_none=True)
    if "category" in fields:
        try:
            fields["category"] = AccountCategory(fields["category"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid category: {fields['category']}") from exc

    entry = await services.update_registry_entry(db, entry_id, staff_id=staff.id, secret=req.secret, **fields)
    if entry is None:
        raise HTTPException(status_code=404, detail="Registry entry not found")
    await db.commit()
    return _to_registry_out(entry)


@router.post("/registry/{entry_id}/reveal", response_model=schemas.SecretRevealOut)
async def reveal_secret(
    entry_id: str,
    request: Request,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    """Highest-sensitivity action in the system — requires an active staff
    (Admin) account, and is always audit-logged whether or not a secret
    exists. There is no stricter room-level tier above this any more (see
    the module docstring)."""
    secret = await services.reveal_secret(db, entry_id, staff_id=staff.id, ip_address=client_ip(request))
    await db.commit()
    if secret is None:
        raise HTTPException(status_code=404, detail="No secret stored for this entry")
    return schemas.SecretRevealOut(id=entry_id, secret=secret)


def _to_registry_out(entry) -> schemas.AccountRegistryOut:
    return schemas.AccountRegistryOut(
        id=entry.id,
        name=entry.name,
        category=entry.category.value,
        provider=entry.provider,
        purpose=entry.purpose,
        owner=entry.owner,
        renewal_date=entry.renewal_date,
        linked_api=entry.linked_api,
        documentation_url=entry.documentation_url,
        has_secret=entry.secret_ciphertext is not None,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


# --- Financial Dashboard ---

@router.get("/financial/records", response_model=list[schemas.FinancialRecordOut])
async def list_financial_records(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_financial_records(db)


@router.post("/financial/records", response_model=schemas.FinancialRecordOut, status_code=status.HTTP_201_CREATED)
async def create_financial_record(
    req: schemas.FinancialRecordCreate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        category = FinancialRecordCategory(req.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid category: {req.category}") from exc

    record = await services.create_financial_record(
        db,
        staff_id=staff.id,
        category=category,
        description=req.description,
        amount=req.amount,
        currency=req.currency,
        incurred_at=req.incurred_at,
        recurring=req.recurring,
        recurrence_period=req.recurrence_period,
        linked_account_registry_id=req.linked_account_registry_id,
    )
    await db.commit()
    return record


@router.get("/financial/summary", response_model=schemas.FinancialSummaryOut)
async def get_financial_summary(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.financial_summary(db)


# --- API Monitor ---

@router.get("/api-monitor", response_model=list[schemas.ApiMonitorOut])
async def list_api_monitor(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_api_monitor_entries(db)


@router.post("/api-monitor", response_model=schemas.ApiMonitorOut, status_code=status.HTTP_201_CREATED)
async def create_api_monitor(
    req: schemas.ApiMonitorCreate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        health = ApiHealthStatus(req.health_status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid health_status: {req.health_status}") from exc

    entry = await services.create_api_monitor_entry(
        db,
        staff_id=staff.id,
        service_name=req.service_name,
        linked_account_registry_id=req.linked_account_registry_id,
        credit_remaining=req.credit_remaining,
        usage_current_period=req.usage_current_period,
        monthly_limit=req.monthly_limit,
        health_status=health,
        notes=req.notes,
    )
    await db.commit()
    return entry


@router.put("/api-monitor/{entry_id}", response_model=schemas.ApiMonitorOut)
async def update_api_monitor(
    entry_id: str,
    req: schemas.ApiMonitorUpdate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    fields = req.model_dump(exclude_none=True)
    if "health_status" in fields:
        try:
            fields["health_status"] = ApiHealthStatus(fields["health_status"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid health_status: {fields['health_status']}") from exc

    entry = await services.update_api_monitor_entry(db, entry_id, staff_id=staff.id, **fields)
    if entry is None:
        raise HTTPException(status_code=404, detail="API monitor entry not found")
    await db.commit()
    return entry


# --- Calendar (Task 1's Calendar Engine — the master calendar's view for this room) ---

@router.get("/calendar", response_model=list[schemas.CalendarEventOut])
async def list_calendar(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await calendar_service.list_for_room(db, RoomName.accounts)


@router.post("/calendar", response_model=schemas.CalendarEventOut, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    req: schemas.CalendarEventCreate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    event = await calendar_service.submit_timing(
        db,
        room=RoomName.accounts,
        kind=req.kind,
        title=req.title,
        due_at=req.due_at,
        description=req.description,
        remind_at=req.remind_at,
        actor_type=ActorType.staff,
        actor_id=staff.id,
    )
    await db.commit()
    return event


# --- Archive Locker ---

@router.get("/archive/{shelf}", response_model=list[schemas.ArchiveItemOut])
async def list_archive_shelf(
    shelf: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    try:
        shelf_enum = ArchiveShelf(shelf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid shelf: {shelf}") from exc
    return await archive_service.list_shelf(db, RoomName.accounts, shelf_enum)


@router.post("/archive", response_model=schemas.ArchiveItemOut, status_code=status.HTTP_201_CREATED)
async def create_archive_item(
    req: schemas.ArchiveItemCreate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    item = await archive_service.create_item(
        db,
        room=RoomName.accounts,
        title=req.title,
        actor_type=ActorType.staff,
        actor_id=staff.id,
        description=req.description,
        item_type=req.item_type,
        content=req.content,
        approved_for_auto_reply=req.approved_for_auto_reply,
    )
    await db.commit()
    return item


# --- Administrative agent ---

@router.get("/administrative-summary", response_model=schemas.AdministrativeSummaryOut)
async def administrative_summary(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.administrative_summary(db)


# --- AI usage ---

@router.get("/ai-usage/summary", response_model=list[schemas.AiUsageSummaryRow])
async def ai_usage_summary(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    """Per-identity token usage across the whole system — who/what is
    actually spending on LLM calls. Recording only; no limit is enforced
    yet, see docs/ARCHITECTURE.md for the intended enforcement hook."""
    return await llm_usage_service.get_usage_summary(db)


@router.get("/ai-usage/by-client-need", response_model=list[schemas.UsageByClientNeedRow])
async def ai_usage_by_client_need(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    """The LLM-tokens drill-down on the Accounts-Room landing dashboard:
    per client, broken out by "need" (action — translation, community
    management, etc.)."""
    return await llm_usage_service.get_usage_by_client_and_action(db)


@router.get("/cost-timeseries", response_model=list[schemas.UsageTimeseriesRow])
async def cost_timeseries(
    bucket: Literal["day", "week"] = "day",
    group_by: Literal["model", "provider", "room", "action"] = "model",
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    """LLM-token cost/usage over time, bucketed and grouped — the
    Accounts-Room landing dashboard's system-cost timeline chart."""
    return await llm_usage_service.get_usage_timeseries(db, bucket=bucket, group_by=group_by)


@router.get("/financial-timeseries", response_model=list[schemas.FinancialTimeseriesRow])
async def financial_timeseries(
    bucket: Literal["day", "week"] = "day", staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    """Manual-expense (hosting, tools, subscriptions, ...) cost over time,
    grouped by category — the non-LLM half of the same landing-dashboard
    chart."""
    return await services.financial_record_timeseries(db, bucket=bucket)
