"""The master calendar (Task 1's Calendar Engine). Every room submits its
own timing through `submit_timing` rather than keeping a private
calendar — this is the one place timing is read from or written to.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.calendar import CalendarEvent
from app.core.models.common import RoomName, utcnow
from app.core.services import audit_service


async def submit_timing(
    db: AsyncSession,
    *,
    room: RoomName,
    kind: str,
    title: str,
    due_at: datetime,
    description: str = "",
    remind_at: datetime | None = None,
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
    actor_type: ActorType = ActorType.system,
    actor_id: str | None = None,
) -> CalendarEvent:
    event = CalendarEvent(
        room=room,
        kind=kind,
        title=title,
        description=description,
        due_at=due_at,
        remind_at=remind_at,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    db.add(event)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="calendar.event.submit",
        room=room,
        entity_type="calendar_event",
        entity_id=event.id,
        after={"kind": kind, "title": title, "due_at": due_at.isoformat()},
    )
    return event


async def list_for_room(db: AsyncSession, room: RoomName, include_resolved: bool = False) -> list[CalendarEvent]:
    stmt = select(CalendarEvent).where(CalendarEvent.room == room)
    if not include_resolved:
        stmt = stmt.where(CalendarEvent.is_resolved.is_(False))
    stmt = stmt.order_by(CalendarEvent.due_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def due_reminders(db: AsyncSession, within: timedelta | None = None) -> list[CalendarEvent]:
    """Events whose reminder window has arrived and hasn't fired yet —
    the Calendar agent's whole job: wake on this, fire, go idle again."""
    now = utcnow()
    horizon = now + within if within else now
    stmt = select(CalendarEvent).where(
        CalendarEvent.reminder_fired.is_(False),
        CalendarEvent.remind_at.is_not(None),
        CalendarEvent.remind_at <= horizon,
        CalendarEvent.is_resolved.is_(False),
    ).order_by(CalendarEvent.remind_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_reminder_fired(db: AsyncSession, event_id: str) -> None:
    event = await db.get(CalendarEvent, event_id)
    if event:
        event.reminder_fired = True
        await db.flush()


async def resolve_event(db: AsyncSession, event_id: str) -> None:
    event = await db.get(CalendarEvent, event_id)
    if event:
        event.is_resolved = True
        await db.flush()
