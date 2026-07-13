"""Task 1 — Accounts room business data: the Account Registry, the
Financial Dashboard's manual expense entries, and the API Monitor.
Calendar, Archive, and the room-account/spend pattern are shared
infrastructure and live in `app.core.models` instead.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class AccountCategory(str, enum.Enum):
    ai_platform = "ai_platform"
    comms_platform = "comms_platform"
    payment = "payment"
    hosting = "hosting"
    domain = "domain"
    government = "government"
    banking = "banking"
    tool = "tool"
    other = "other"


class AccountRegistryEntry(Base):
    """Every account UNIFIC uses. `secret_ciphertext` is Fernet-encrypted
    at rest and is only ever decrypted through the explicit `reveal`
    action in `services.py` — never included in any agent/LLM payload."""

    __tablename__ = "account_registry_entry"
    __table_args__ = {"schema": "accounts"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[AccountCategory] = mapped_column(Enum(AccountCategory, name="account_category"), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(255), default="")
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    linked_api: Mapped[str] = mapped_column(String(255), default="")
    documentation_url: Mapped[str] = mapped_column(String(1000), default="")
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class FinancialRecordCategory(str, enum.Enum):
    subscription = "subscription"
    salary = "salary"
    contractor = "contractor"
    api_usage = "api_usage"
    hosting = "hosting"
    other = "other"


class FinancialRecord(Base):
    """A manual expense entry — salaries, contractor invoices,
    subscriptions. Automatic agent API spend is recorded separately by
    `core.spend_service` into `core.ledger_entry`; the Financial
    Dashboard reads both."""

    __tablename__ = "financial_record"
    __table_args__ = {"schema": "accounts"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    category: Mapped[FinancialRecordCategory] = mapped_column(
        Enum(FinancialRecordCategory, name="financial_record_category"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="AUD")
    incurred_at: Mapped[date] = mapped_column(Date, nullable=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_period: Mapped[str] = mapped_column(String(50), default="")
    linked_account_registry_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.account_registry_entry.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ApiHealthStatus(str, enum.Enum):
    healthy = "healthy"
    degraded = "degraded"
    down = "down"
    unknown = "unknown"


class ApiMonitorEntry(Base):
    __tablename__ = "api_monitor_entry"
    __table_args__ = {"schema": "accounts"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    linked_account_registry_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.account_registry_entry.id", ondelete="SET NULL"), nullable=True
    )
    credit_remaining: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    usage_current_period: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    monthly_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    health_status: Mapped[ApiHealthStatus] = mapped_column(
        Enum(ApiHealthStatus, name="api_health_status"), default=ApiHealthStatus.unknown
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
