"""Staff (master dashboard) authentication.

There is deliberately no open self-registration endpoint for staff: master-
dashboard accounts are provisioned, not signed up for. The very first
staff account is created via `/bootstrap` (which refuses to run once any
staff account exists) and is always `tier=admin`; every subsequent staff
account is created by an existing Admin via `/staff` (`Depends(require_admin)`)
— an Admin can provision either another Admin or a regular Staff account
(see `app.core.security.dependencies` for the two-tier model).

Clients, unlike staff, DO have a self-registration path — see
`app.profiles.router`'s public router (`POST /api/profiles/public/client-signup`)
and the Admin approval queue (`GET/POST /api/profiles/registration-requests`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    AccessTokenResponse,
    StaffBootstrapRequest,
    StaffCreateRequest,
    StaffLoginRequest,
    StaffOut,
)
from app.core.models.audit import ActorType
from app.core.models.staff import RefreshToken, StaffCategory, StaffTier, StaffUser
from app.core.services import audit_service
from app.core.security.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.core.security.dependencies import client_ip, require_admin, require_any_staff
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
        tier=StaffTier.admin,
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
async def me(current_staff: StaffUser = Depends(require_any_staff)):
    return StaffOut.model_validate(current_staff)


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    req: StaffCreateRequest,
    current_staff: StaffUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Only an Admin reaches this route at all (`Depends(require_admin)`),
    so an Admin may provision either another Admin or a regular Staff
    account — there's no separate gatekeeper role above Admin."""
    existing = await db.execute(select(StaffUser).where(StaffUser.email == req.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    try:
        tier = StaffTier(req.tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="tier must be 'admin' or 'staff'") from exc

    if req.category_id is not None:
        category = await db.get(StaffCategory, req.category_id)
        if category is None:
            raise HTTPException(status_code=400, detail="Unknown category_id")

    new_staff = StaffUser(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        tier=tier,
        category_id=req.category_id,
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
        after={"email": new_staff.email, "full_name": new_staff.full_name, "tier": tier.value},
    )
    await db.commit()
    return StaffOut.model_validate(new_staff)
