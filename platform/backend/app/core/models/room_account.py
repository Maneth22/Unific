"""Every room has its own account, with one sub-account per agent, so
spend is always traceable to the agent that incurred it. This is the
"room contract" piece Tasks 4-8 will reuse without modification.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import RoomName, utcnow, uuid_str
from app.database import Base


class RoomAccount(Base):
    __tablename__ = "room_account"
    __table_args__ = (
        Index("ix_room_account_room", "room", unique=True),
        {"schema": "core"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    agent_sub_accounts: Mapped[list["AgentSubAccount"]] = relationship(
        back_populates="room_account", cascade="all, delete-orphan"
    )


class AgentSubAccount(Base):
    __tablename__ = "agent_sub_account"
    __table_args__ = (
        Index("ix_agent_sub_account_room_agent", "room_account_id", "agent_name", unique=True),
        {"schema": "core"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    room_account_id: Mapped[str] = mapped_column(
        ForeignKey("core.room_account.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    room_account: Mapped["RoomAccount"] = relationship(back_populates="agent_sub_accounts")
