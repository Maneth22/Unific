"""A simpler replacement for the old `llm_usage_record` — one row per
LLM/agent call anywhere in the app (WhatsApp reply drafting, translation,
tone analysis, report generation, live meeting captioning), regardless of
which pillar it belongs to.

Table only in this phase — no call sites write to it yet. Instrumenting
every provider call site to actually write here is the Staff
Observability & WhatsApp Test Console phase's job (see docs/
PHASE_1_NOTES.md's roadmap), once the Agent Console needs data to show.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class AgentRunStatus(str, enum.Enum):
    """A placeholder set — the phase that actually writes to this table
    will know the real statuses its call sites need."""

    success = "success"
    error = "error"
    timeout = "timeout"


class AgentRunLog(Base):
    __tablename__ = "agent_run_log"
    __table_args__ = (
        Index("ix_agent_run_log_org_created", "org_id", "created_at"),
        Index("ix_agent_run_log_status_created", "status", "created_at"),
        {"schema": "core"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    # Nullable: not every run is org-scoped (a staff-triggered test-console
    # send, or a system-level job, may have no org).
    org_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.org.id", ondelete="SET NULL"), nullable=True, index=True)
    plugin_key: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_template_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(Enum(AgentRunStatus, name="agent_run_status"), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
