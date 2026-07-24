from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    assigned_to_staff_id: str
    due_date: date | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    assigned_by_staff_id: str | None
    assigned_to_staff_id: str
    status: str
    due_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskUpdateCreate(BaseModel):
    note: str
    progress_status: str | None = None
    is_concern: bool = False


class TaskUpdateOut(BaseModel):
    id: str
    task_id: str
    author_staff_id: str | None
    note: str
    progress_status: str | None
    is_concern: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskDetailOut(TaskOut):
    updates: list[TaskUpdateOut]


class TaskDashboardRowOut(TaskOut):
    """One row in the admin's task dashboard — the task plus whatever its
    newest update says, so pending work / latest status / concerns are
    all visible without opening each task."""

    latest_update: TaskUpdateOut | None = None


class InboxMessageCreate(BaseModel):
    # Exactly one of these two — a staff member messaging a colleague/
    # admin, or an admin replying to a client's notice.
    recipient_staff_id: str | None = None
    recipient_client_id: str | None = None
    subject: str = ""
    body: str
    related_task_id: str | None = None


class InboxMessageOut(BaseModel):
    id: str
    sender_staff_id: str | None
    sender_client_id: str | None
    recipient_staff_id: str | None
    recipient_client_id: str | None
    subject: str
    body: str
    related_task_id: str | None
    related_meeting_id: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
