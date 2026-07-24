"""Admin-managed staff categories + the Profiles Room's staff directory."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.staff import StaffUser
from app.core.security.dependencies import require_admin, require_any_staff
from app.database import get_db
from app.staff_directory import schemas, services

router = APIRouter(prefix="/api/staff-directory", tags=["staff_directory"])


@router.post("/categories", response_model=schemas.StaffCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    req: schemas.StaffCategoryCreate, staff: StaffUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    try:
        category = await services.create_category(db, name=req.name, description=req.description, staff_id=staff.id)
    except services.StaffDirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return category


@router.get("/categories", response_model=list[schemas.StaffCategoryOut])
async def list_categories(staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    return await services.list_categories(db)


@router.get("/staff", response_model=list[schemas.StaffDirectoryEntryOut])
async def list_staff(staff: StaffUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await services.list_staff_directory(db)


@router.get("/staff/lite", response_model=list[schemas.StaffDirectoryLiteOut])
async def list_staff_lite(staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    return await services.list_staff_lite(db)


@router.patch("/staff/{staff_id}", response_model=schemas.StaffDirectoryEntryOut)
async def update_staff(
    staff_id: str,
    req: schemas.StaffUpdateRequest,
    staff: StaffUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await services.update_staff(
            db, staff_id, actor_id=staff.id, tier=req.tier, category_id=req.category_id, is_active=req.is_active
        )
    except services.StaffDirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    rows = await services.list_staff_directory(db)
    updated = next(r for r in rows if r["id"] == staff_id)
    return updated
