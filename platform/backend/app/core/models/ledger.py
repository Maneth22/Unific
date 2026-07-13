"""The one append-only financial ledger.

Every token movement anywhere in the system — an ID funding a sub-ID, an
agent spending against its sub-account, a top-up — writes one row here.
This is deliberately the same table for all of it (per the Token/Ledger/
Intelligence-Map note: build the ledger once, everything else reads from
it) and stands in for Task 8 (Hold Data) until that room is built.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import RoomName, utcnow
from app.database import Base


class LedgerEntryType(str, enum.Enum):
    funding = "funding"                    # a group funds itself or a child identity
    customer_transfer = "customer_transfer"  # credit trickles from a parent identity to a child
    agent_spend = "agent_spend"            # a room's own agent sub-account spends (UNIFIC's operating cost)
    gate_charge = "gate_charge"            # an identity's own balance is charged for a paid action past the gate
    adjustment = "adjustment"              # manual correction, always human-authorised


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(LedgerEntryType, name="ledger_entry_type"), nullable=False, index=True
    )
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    audit_log_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.audit_log.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
