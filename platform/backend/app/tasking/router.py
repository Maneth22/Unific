"""Staff task assignment/progress and the internal inbox. Assigning and
the admin dashboard view are admin-only; a staff member's own tasks,
updates, and inbox use `require_any_staff` — both tiers use these."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.staff import StaffTier, StaffUser
from app.core.security.dependencies import require_admin, require_any_staff
from app.database import get_db
from app.tasking import schemas, services

router = APIRouter(prefix="/api/tasking", tags=["tasking"])


def _dashboard_row(task, latest_update) -> schemas.TaskDashboardRowOut:
    return schemas.TaskDashboardRowOut(
        **schemas.TaskOut.model_validate(task).model_dump(),
        latest_update=schemas.TaskUpdateOut.model_validate(latest_update) if latest_update else None,
    )


@router.post("/tasks", response_model=schemas.TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(req: schemas.TaskCreate, staff: StaffUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    task = await services.create_task(
        db,
        title=req.title,
        description=req.description,
        assigned_to_staff_id=req.assigned_to_staff_id,
        assigned_by_staff_id=staff.id,
        due_date=req.due_date,
    )
    await db.commit()
    return task


@router.get("/tasks", response_model=list[schemas.TaskDashboardRowOut])
async def list_tasks_dashboard(staff: StaffUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = await services.list_all_tasks_with_latest_update(db)
    return [_dashboard_row(r["task"], r["latest_update"]) for r in rows]


@router.get("/tasks/concerns", response_model=list[schemas.TaskUpdateOut])
async def list_concerns(staff: StaffUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await services.list_open_concerns(db)


@router.get("/tasks/mine", response_model=list[schemas.TaskOut])
async def list_my_tasks(staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    return await services.list_my_tasks(db, staff.id)


@router.get("/tasks/{task_id}", response_model=schemas.TaskDetailOut)
async def get_task(task_id: str, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    try:
        task = await services.get_task_with_updates(db, task_id, staff_id=staff.id, is_admin=staff.tier == StaffTier.admin)
    except services.TaskingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return task


@router.post("/tasks/{task_id}/updates", response_model=schemas.TaskUpdateOut, status_code=status.HTTP_201_CREATED)
async def add_task_update(
    task_id: str, req: schemas.TaskUpdateCreate, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)
):
    try:
        update = await services.add_task_update(
            db,
            task_id,
            author_staff_id=staff.id,
            is_admin=staff.tier == StaffTier.admin,
            note=req.note,
            progress_status=req.progress_status,
            is_concern=req.is_concern,
        )
    except services.TaskingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return update


# --- Inbox ---

@router.post("/inbox", response_model=schemas.InboxMessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(req: schemas.InboxMessageCreate, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    try:
        message = await services.send_message(
            db,
            sender_staff_id=staff.id,
            recipient_staff_id=req.recipient_staff_id,
            recipient_client_id=req.recipient_client_id,
            subject=req.subject,
            body=req.body,
            related_task_id=req.related_task_id,
        )
    except services.TaskingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return message


@router.get("/inbox", response_model=list[schemas.InboxMessageOut])
async def list_inbox(staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    return await services.list_inbox_for_staff(db, staff.id)


@router.patch("/inbox/{message_id}/read", response_model=schemas.InboxMessageOut)
async def mark_message_read(message_id: str, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    try:
        message = await services.mark_message_read(db, message_id, staff_id=staff.id)
    except services.TaskingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return message
