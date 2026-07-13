"""Records and summarizes LLM provider usage. The single write path
(`record_usage`) is called from inside each Gemini provider implementation
after a call completes — see `app.core.providers.gemini_reply_generator`
and `gemini_translation_provider`. Mock/stub providers never call this,
so usage stats only ever reflect real LLM spend.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName
from app.core.models.llm_usage import LlmUsageRecord
from app.profiles.models import Identity


async def record_usage(
    db: AsyncSession,
    *,
    room: RoomName,
    agent_name: str,
    identity_id: str | None,
    provider: str,
    model: str,
    action: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    estimated_cost: Decimal | None = None,
) -> LlmUsageRecord:
    record = LlmUsageRecord(
        room=room,
        agent_name=agent_name,
        identity_id=identity_id,
        provider=provider,
        model=model,
        action=action,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost=estimated_cost,
    )
    db.add(record)
    await db.flush()
    return record


async def get_usage_summary(
    db: AsyncSession, since: datetime | None = None, identity_ids: list[str] | None = None
) -> list[dict]:
    """Per-identity totals, highest usage first — the "who's using the
    most tokens" view. `identity_ids` scopes the summary to a subtree
    (the client-dashboard case); None means system-wide (staff)."""
    stmt = (
        select(
            LlmUsageRecord.identity_id,
            Identity.name,
            func.count(LlmUsageRecord.id).label("call_count"),
            func.coalesce(func.sum(LlmUsageRecord.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LlmUsageRecord.estimated_cost), 0).label("total_cost"),
        )
        .outerjoin(Identity, Identity.id == LlmUsageRecord.identity_id)
        .group_by(LlmUsageRecord.identity_id, Identity.name)
        .order_by(func.coalesce(func.sum(LlmUsageRecord.total_tokens), 0).desc())
    )
    if since is not None:
        stmt = stmt.where(LlmUsageRecord.created_at >= since)
    if identity_ids is not None:
        stmt = stmt.where(LlmUsageRecord.identity_id.in_(identity_ids))
    result = await db.execute(stmt)
    return [
        {
            "identity_id": row.identity_id,
            "identity_name": row.name,
            "call_count": row.call_count,
            "total_tokens": row.total_tokens,
            "total_cost": row.total_cost,
        }
        for row in result.all()
    ]


async def get_usage_for_identity(db: AsyncSession, identity_id: str, limit: int = 50) -> dict:
    totals_stmt = select(
        func.count(LlmUsageRecord.id),
        func.coalesce(func.sum(LlmUsageRecord.total_tokens), 0),
        func.coalesce(func.sum(LlmUsageRecord.estimated_cost), 0),
    ).where(LlmUsageRecord.identity_id == identity_id)
    totals_result = await db.execute(totals_stmt)
    call_count, total_tokens, total_cost = totals_result.one()

    recent_stmt = (
        select(LlmUsageRecord)
        .where(LlmUsageRecord.identity_id == identity_id)
        .order_by(LlmUsageRecord.created_at.desc())
        .limit(limit)
    )
    recent_result = await db.execute(recent_stmt)

    return {
        "identity_id": identity_id,
        "call_count": call_count,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "recent": list(recent_result.scalars().all()),
    }
