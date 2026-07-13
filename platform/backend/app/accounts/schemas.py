from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# --- Account Registry ---

class AccountRegistryCreate(BaseModel):
    name: str
    category: str
    provider: str = ""
    purpose: str = ""
    owner: str = ""
    renewal_date: date | None = None
    linked_api: str = ""
    documentation_url: str = ""
    secret: str | None = Field(default=None, description="Plaintext secret — encrypted before storage, never echoed back")


class AccountRegistryUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    provider: str | None = None
    purpose: str | None = None
    owner: str | None = None
    renewal_date: date | None = None
    linked_api: str | None = None
    documentation_url: str | None = None
    secret: str | None = None


class AccountRegistryOut(BaseModel):
    id: str
    name: str
    category: str
    provider: str
    purpose: str
    owner: str
    renewal_date: date | None
    linked_api: str
    documentation_url: str
    has_secret: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SecretRevealOut(BaseModel):
    id: str
    secret: str


# --- Financial Record ---

class FinancialRecordCreate(BaseModel):
    category: str
    description: str
    amount: Decimal
    currency: str = "AUD"
    incurred_at: date
    recurring: bool = False
    recurrence_period: str = ""
    linked_account_registry_id: str | None = None


class FinancialRecordOut(BaseModel):
    id: str
    category: str
    description: str
    amount: Decimal
    currency: str
    incurred_at: date
    recurring: bool
    recurrence_period: str
    linked_account_registry_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FinancialSummaryOut(BaseModel):
    total_manual_expenses: Decimal
    total_agent_spend: Decimal
    by_category: dict[str, Decimal]
    room_summaries: list[dict]


# --- API Monitor ---

class ApiMonitorCreate(BaseModel):
    service_name: str
    linked_account_registry_id: str | None = None
    credit_remaining: Decimal | None = None
    usage_current_period: Decimal | None = None
    monthly_limit: Decimal | None = None
    health_status: str = "unknown"
    notes: str = ""


class ApiMonitorUpdate(BaseModel):
    credit_remaining: Decimal | None = None
    usage_current_period: Decimal | None = None
    monthly_limit: Decimal | None = None
    health_status: str | None = None
    notes: str | None = None


class ApiMonitorOut(BaseModel):
    id: str
    service_name: str
    linked_account_registry_id: str | None
    credit_remaining: Decimal | None
    usage_current_period: Decimal | None
    monthly_limit: Decimal | None
    health_status: str
    last_checked_at: datetime | None
    notes: str
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Calendar (thin passthrough to core.calendar_service) ---

class CalendarEventCreate(BaseModel):
    kind: str
    title: str
    due_at: datetime
    description: str = ""
    remind_at: datetime | None = None


class CalendarEventOut(BaseModel):
    id: str
    room: str
    kind: str
    title: str
    description: str
    due_at: datetime
    remind_at: datetime | None
    reminder_fired: bool
    is_resolved: bool

    model_config = {"from_attributes": True}


# --- Archive (thin passthrough to core.archive_service) ---

class ArchiveItemCreate(BaseModel):
    title: str
    description: str = ""
    item_type: str = "document"
    content: dict = Field(default_factory=dict)
    approved_for_auto_reply: bool = False


class ArchiveItemOut(BaseModel):
    id: str
    room: str
    shelf: str
    status: str
    title: str
    description: str
    item_type: str
    source_room: str | None
    target_room: str | None
    approved_for_auto_reply: bool
    version: int
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Administrative agent ---

class AdministrativeSummaryOut(BaseModel):
    upcoming_renewals: list[CalendarEventOut]
    services_needing_attention: list[ApiMonitorOut]
    financial_summary: FinancialSummaryOut


# --- AI usage ---

class AiUsageSummaryRow(BaseModel):
    identity_id: str | None
    identity_name: str | None
    call_count: int
    total_tokens: int
    total_cost: Decimal
