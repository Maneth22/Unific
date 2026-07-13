"""Staff (master dashboard) authentication.

There is deliberately no open self-registration endpoint: Task 1 is "the
crown jewels" and master dashboards are provisioned, not signed up for.
The very first staff account is created via `/bootstrap` (which refuses
to run once any staff account exists); every subsequent staff account is
created by a superadmin via `/staff`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    AccessTokenResponse,
    RoomAccessGrantRequest,
    StaffBootstrapRequest,
    StaffCreateRequest,
    StaffLoginRequest,
    StaffOut,
)
from app.core.models.audit import ActorType
from app.core.models.common import RoomName, RoomPermission
from app.core.models.staff import RefreshToken, StaffRoomAccess, StaffUser
from app.core.services import audit_service
from app.core.security.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.core.security.dependencies import client_ip, get_current_staff_user
from app.core.security.password import hash_password, verify_password
from app.core.security.rate_limit import is_locked_out, record_login_attempt
from app.core.security.tokens import hash_refresh_token
from app.core.services.token_service import issue_tokens, revoke_refresh_token, rotate_refresh_token
from app.database import get_db

router = APIRouter(prefix="/api/auth/staff", tags=["auth:staff"])


@router.post("/bootstrap", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap(req: StaffBootstrapRequest, response: Response, db: AsyncSession = Depends(get_db)):
    existing_count = await db.execute(select(StaffUser.id).limit(1))
    if existing_count.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bootstrap already completed")

    staff = StaffUser(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        is_superadmin=True,
    )
    db.add(staff)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.system,
        actor_id=staff.id,
        action="staff.bootstrap",
        entity_type="staff_user",
        entity_id=staff.id,
    )

    tokens = await issue_tokens(db, audience="staff", staff_user_id=staff.id)
    await db.commit()
    await db.refresh(staff, attribute_names=["room_access"])

    set_refresh_cookie(response, tokens.raw_refresh_token, tokens.refresh_expires_at_seconds)
    return AccessTokenResponse(access_token=tokens.access_token, staff=StaffOut.model_validate(staff))


@router.post("/login", response_model=AccessTokenResponse)
async def login(req: StaffLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = req.email.lower()
    ip = client_ip(request)

    if await is_locked_out(db, email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts — try again later",
        )

    result = await db.execute(select(StaffUser).where(StaffUser.email == email))
    staff = result.scalar_one_or_none()

    valid = staff is not None and staff.is_active and verify_password(req.password, staff.password_hash)
    await record_login_attempt(db, email, success=valid, ip_address=ip)

    if not valid:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff.id,
        action="staff.login",
        entity_type="staff_user",
        entity_id=staff.id,
        ip_address=ip,
    )

    tokens = await issue_tokens(db, audience="staff", staff_user_id=staff.id)
    await db.commit()
    await db.refresh(staff, attribute_names=["room_access"])

    set_refresh_cookie(response, tokens.raw_refresh_token, tokens.refresh_expires_at_seconds)
    return AccessTokenResponse(access_token=tokens.access_token, staff=StaffOut.model_validate(staff))


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    rotated = await rotate_refresh_token(db, raw_token)
    if rotated is None:
        clear_refresh_cookie(response)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or expired")

    old_token, new_tokens = rotated
    if old_token.staff_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a staff session")

    result = await db.execute(select(StaffUser).where(StaffUser.id == old_token.staff_user_id))
    staff = result.scalar_one_or_none()
    if staff is None or not staff.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")

    await db.commit()
    await db.refresh(staff, attribute_names=["room_access"])

    set_refresh_cookie(response, new_tokens.raw_refresh_token, new_tokens.refresh_expires_at_seconds)
    return AccessTokenResponse(access_token=new_tokens.access_token, staff=StaffOut.model_validate(staff))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token:
        token_hash = hash_refresh_token(raw_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        existing = result.scalar_one_or_none()
        await revoke_refresh_token(db, raw_token)
        if existing is not None and existing.staff_user_id is not None:
            await audit_service.record(
                db,
                actor_type=ActorType.staff,
                actor_id=existing.staff_user_id,
                action="staff.logout",
                entity_type="staff_user",
                entity_id=existing.staff_user_id,
            )
        await db.commit()
    clear_refresh_cookie(response)


@router.get("/me", response_model=StaffOut)
async def me(current_staff: StaffUser = Depends(get_current_staff_user), db: AsyncSession = Depends(get_db)):
    await db.refresh(current_staff, attribute_names=["room_access"])
    return StaffOut.model_validate(current_staff)


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    req: StaffCreateRequest,
    current_staff: StaffUser = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_staff.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin only")

    existing = await db.execute(select(StaffUser).where(StaffUser.email == req.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    new_staff = StaffUser(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name,
    )
    db.add(new_staff)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=current_staff.id,
        action="staff.create",
        entity_type="staff_user",
        entity_id=new_staff.id,
        after={"email": new_staff.email, "full_name": new_staff.full_name},
    )
    await db.commit()
    await db.refresh(new_staff, attribute_names=["room_access"])
    return StaffOut.model_validate(new_staff)


@router.post("/staff/{staff_id}/room-access", response_model=StaffOut)
async def grant_room_access(
    staff_id: str,
    req: RoomAccessGrantRequest,
    current_staff: StaffUser = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_staff.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin only")

    try:
        room = RoomName(req.room)
        permission = RoomPermission(req.permission)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    result = await db.execute(select(StaffUser).where(StaffUser.id == staff_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff user not found")

    existing = await db.execute(
        select(StaffRoomAccess).where(
            StaffRoomAccess.staff_user_id == staff_id, StaffRoomAccess.room == room
        )
    )
    access = existing.scalar_one_or_none()
    if access is not None:
        access.permission = permission
    else:
        access = StaffRoomAccess(
            staff_user_id=staff_id, room=room, permission=permission, granted_by=current_staff.id
        )
        db.add(access)
    await db.flush()

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=current_staff.id,
        action="staff.room_access.grant",
        room=room,
        entity_type="staff_user",
        entity_id=staff_id,
        after={"room": room.value, "permission": permission.value},
    )
    await db.commit()
    await db.refresh(target, attribute_names=["room_access"])
    return StaffOut.model_validate(target)
