"""Records every LLM provider call — the "see usage per user" and future
"add limitations" requirement. One row per call, keyed to the identity
that triggered it (nullable, since a future staff-facing agent call might
not be identity-scoped) so usage can be summed per member/group and,
later, checked by `core.gate_service` against a cap before a call is
made — that enforcement isn't built yet; this table is what it will read.

`member_id` (UNIFIC v2's flat `orgs.Member`, additive alongside
`identity_id` rather than replacing it — see docs/PHASE_2_NOTES.md) is
the new pipeline's equivalent principal. At most one of the two is ever
set: a call is triggered by either the old identity-tree member or the
new orgs.Member, never both. Kept as two nullable FKs rather than one
polymorphic column so each stays a real, simple FK — no lookup-by-type
indirection needed to join back to whichever table actually owns the row.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import RoomName, utcnow, uuid_str
from app.database import Base


class LlmUsageRecord(Base):
    __tablename__ = "llm_usage_record"
    __table_args__ = (
        CheckConstraint(
            "identity_id IS NULL OR member_id IS NULL",
            name="ck_llm_usage_record_single_principal",
        ),
        {"schema": "core"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    room: Mapped[RoomName] = mapped_column(Enum(RoomName, name="room_name"), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="SET NULL"), nullable=True, index=True
    )
    member_id: Mapped[str | None] = mapped_column(
        ForeignKey("orgs.member.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # reply_generation | translation | language_detection
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
