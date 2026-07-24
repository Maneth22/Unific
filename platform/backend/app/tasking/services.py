"""Staff task assignment/progress-tracking and the internal inbox — the
"common interface" regular staff use (see `app.tasking.models`)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.models.audit import ActorType
from app.core.services import audit_service
from app.tasking.models import InboxMessage, Task, TaskStatus, TaskUpdate


class TaskingError(Exception):
    pass


async def create_task(
    db: AsyncSession, *, title: str, description: str, assigned_to_staff_id: str, assigned_by_staff_id: str, due_date: date | None
) -> Task:
    task = Task(
        title=title,
        description=description,
        assigned_to_staff_id=assigned_to_staff_id,
        assigned_by_staff_id=assigned_by_staff_id,
        due_date=due_date,
    )
    db.add(task)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=assigned_by_staff_id,
        action="tasking.task.create",
        entity_type="task",
        entity_id=task.id,
        after={"title": title, "assigned_to_staff_id": assigned_to_staff_id},
    )
    return task


async def list_all_tasks_with_latest_update(db: AsyncSession) -> list[dict]:
    """The admin dashboard view: every task plus its newest update (if
    any), via `DISTINCT ON` — one row per task, no N+1."""
    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    tasks = list(result.scalars().all())
    if not tasks:
        return []

    latest_result = await db.execute(
        select(TaskUpdate)
        .distinct(TaskUpdate.task_id)
        .where(TaskUpdate.task_id.in_([t.id for t in tasks]))
        .order_by(TaskUpdate.task_id, TaskUpdate.created_at.desc())
    )
    latest_by_task = {u.task_id: u for u in latest_result.scalars().all()}
    return [{"task": t, "latest_update": latest_by_task.get(t.id)} for t in tasks]


async def list_open_concerns(db: AsyncSession) -> list[TaskUpdate]:
    result = await db.execute(
        select(TaskUpdate).where(TaskUpdate.is_concern.is_(True)).order_by(TaskUpdate.created_at.desc())
    )
    return list(result.scalars().all())


async def list_my_tasks(db: AsyncSession, staff_id: str) -> list[Task]:
    result = await db.execute(
        select(Task).where(Task.assigned_to_staff_id == staff_id).order_by(Task.created_at.desc())
    )
    return list(result.scalars().all())


async def get_task_with_updates(db: AsyncSession, task_id: str, *, staff_id: str, is_admin: bool) -> Task:
    result = await db.execute(
        select(Task).options(selectinload(Task.updates)).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise TaskingError("Task not found")
    if not is_admin and task.assigned_to_staff_id != staff_id:
        raise TaskingError("This task is not assigned to you")
    return task


async def add_task_update(
    db: AsyncSession, task_id: str, *, author_staff_id: str, is_admin: bool, note: str, progress_status: str | None, is_concern: bool
) -> TaskUpdate:
    task = await db.get(Task, task_id)
    if task is None:
        raise TaskingError("Task not found")
    if not is_admin and task.assigned_to_staff_id != author_staff_id:
        raise TaskingError("This task is not assigned to you")

    parsed_status = None
    if progress_status is not None:
        try:
            parsed_status = TaskStatus(progress_status)
        except ValueError as exc:
            raise TaskingError("progress_status must be a valid task status") from exc
        task.status = parsed_status

    update = TaskUpdate(
        task_id=task_id, author_staff_id=author_staff_id, note=note, progress_status=parsed_status, is_concern=is_concern
    )
    db.add(update)
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=author_staff_id,
        action="tasking.task.update",
        entity_type="task",
        entity_id=task_id,
        after={"is_concern": is_concern, "progress_status": parsed_status.value if parsed_status else None},
    )
    await db.flush()
    return update


# --- Inbox ---

async def send_message(
    db: AsyncSession,
    *,
    sender_staff_id: str | None = None,
    sender_client_id: str | None = None,
    recipient_staff_id: str | None = None,
    recipient_client_id: str | None = None,
    subject: str,
    body: str,
    related_task_id: str | None = None,
    related_meeting_id: str | None = None,
) -> InboxMessage:
    if (recipient_staff_id is None) == (recipient_client_id is None):
        raise TaskingError("Exactly one of recipient_staff_id or recipient_client_id must be set")
    message = InboxMessage(
        sender_staff_id=sender_staff_id,
        sender_client_id=sender_client_id,
        recipient_staff_id=recipient_staff_id,
        recipient_client_id=recipient_client_id,
        subject=subject,
        body=body,
        related_task_id=related_task_id,
        related_meeting_id=related_meeting_id,
    )
    db.add(message)
    await db.flush()
    return message


async def send_client_notice_to_admins(
    db: AsyncSession, *, sender_client_id: str, subject: str, body: str
) -> list[InboxMessage]:
    """A client's notice/concern has no single fixed "the admin" to
    address — fan out one message per active admin rather than inventing
    a broadcast-recipient concept in the schema."""
    from app.core.models.staff import StaffTier, StaffUser

    result = await db.execute(select(StaffUser.id).where(StaffUser.tier == StaffTier.admin, StaffUser.is_active.is_(True)))
    admin_ids = [row[0] for row in result.all()]
    messages = []
    for admin_id in admin_ids:
        messages.append(
            await send_message(
                db, sender_client_id=sender_client_id, recipient_staff_id=admin_id, subject=subject, body=body
            )
        )
    return messages


async def list_inbox_for_client(db: AsyncSession, client_id: str) -> list[InboxMessage]:
    result = await db.execute(
        select(InboxMessage).where(InboxMessage.recipient_client_id == client_id).order_by(InboxMessage.created_at.desc())
    )
    return list(result.scalars().all())


async def mark_message_read_for_client(db: AsyncSession, message_id: str, *, client_id: str) -> InboxMessage:
    from app.core.models.common import utcnow

    message = await db.get(InboxMessage, message_id)
    if message is None or message.recipient_client_id != client_id:
        raise TaskingError("Message not found")
    if message.read_at is None:
        message.read_at = utcnow()
    return message


async def list_inbox_for_staff(db: AsyncSession, staff_id: str) -> list[InboxMessage]:
    result = await db.execute(
        select(InboxMessage).where(InboxMessage.recipient_staff_id == staff_id).order_by(InboxMessage.created_at.desc())
    )
    return list(result.scalars().all())


async def mark_message_read(db: AsyncSession, message_id: str, *, staff_id: str) -> InboxMessage:
    from app.core.models.common import utcnow

    message = await db.get(InboxMessage, message_id)
    if message is None or message.recipient_staff_id != staff_id:
        raise TaskingError("Message not found")
    if message.read_at is None:
        message.read_at = utcnow()
    return message
