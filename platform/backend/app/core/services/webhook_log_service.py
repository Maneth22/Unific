"""The single write path into `core.webhook_log`. Every inbound webhook
POST and every outbound test-send writes here regardless of whether
downstream processing succeeded — see `WebhookLog`'s docstring. Mirrors
`audit_service.record`'s "one write path" shape.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName
from app.core.models.webhook_log import WebhookDirection, WebhookLog


async def record(
    db: AsyncSession,
    *,
    room: RoomName,
    provider: str,
    direction: WebhookDirection,
    raw_payload: dict,
    status: str,
) -> WebhookLog:
    entry = WebhookLog(room=room, provider=provider, direction=direction, raw_payload=raw_payload, status=status)
    db.add(entry)
    await db.flush()
    return entry


async def list_recent(db: AsyncSession, *, limit: int = 50) -> list[WebhookLog]:
    result = await db.execute(select(WebhookLog).order_by(WebhookLog.created_at.desc()).limit(limit))
    return list(result.scalars().all())
