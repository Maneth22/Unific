"""`orgs` schema API. Staff routes are gated by `require_admin` (reused
verbatim from `app.core.security.dependencies`); org-user routes are
gated by `app.orgs.security`'s new dependencies. Mirrors
`app.profiles.router`'s shape (public/staff/client-router split) for the
new flat Org/Group/Member/OrgUser model — additive alongside the
untouched `app.profiles.router`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.audit import ActorType
from app.core.rate_limit import limiter
from app.core.security.cookies import (
    ORG_COOKIE_PATH,
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    set_refresh_cookie,
)
from app.core.models.staff import RefreshToken
from app.core.security.dependencies import client_ip, require_admin
from app.core.security.password import hash_password, needs_rehash, verify_password
from app.core.security.rate_limit import is_locked_out, record_login_attempt
from app.core.security.tokens import hash_refresh_token
from app.core.services import audit_service
from app.core.services.token_service import issue_tokens, revoke_refresh_token, rotate_refresh_token
from app.database import get_db
from app.orgs import schemas, services
from app.orgs.models import Group, OrgRegistrationStatus, OrgUser, OrgUserRole
from app.orgs.security import assert_in_org, get_current_org_user, require_org_owner

# ============================= Public routes =============================

public_router = APIRouter(prefix="/api/orgs/public", tags=["orgs:public"])


@public_router.post("/register", response_model=schemas.OrgSignupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_webhook)
async def public_org_signup(request: Request, req: schemas.OrgSignupRequest, db: AsyncSession = Depends(get_db)):
    try:
        registration = await services.submit_org_registration(
            db, org_name=req.org_name, contact_name=req.contact_name, email=req.email, password=req.password
        )
    except services.OrgsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return schemas.OrgSignupOut(id=registration.id, status=registration.status.value)


# ============================= Staff (admin) routes =============================

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


@router.get("/registration-requests", response_model=list[schemas.OrgRegistrationRequestOut])
async def list_org_registration_requests(
    status_filter: str | None = None,
    staff=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    parsed_status = None
    if status_filter:
        try:
            parsed_status = OrgRegistrationStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}") from exc
    return await services.list_org_registration_requests(db, status=parsed_status)


@router.post("/registration-requests/{request_id}/approve", response_model=schemas.OrgUserOut)
async def approve_org_registration_request(
    request_id: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    try:
        owner = await services.approve_org_registration(db, request_id, actor_id=staff.id)
    except services.OrgsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return owner


@router.post("/registration-requests/{request_id}/reject", response_model=schemas.OrgRegistrationRequestOut)
async def reject_org_registration_request(
    request_id: str,
    req: schemas.OrgRegistrationRejectRequest,
    staff=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        registration = await services.reject_org_registration(db, request_id, actor_id=staff.id, reason=req.reason)
    except services.OrgsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return registration


# ============================= Org-user auth =============================

client_router = APIRouter(prefix="/api/orgs/client", tags=["orgs:client"])


@client_router.post("/login", response_model=schemas.OrgAccessTokenResponse)
async def org_login(req: schemas.OrgLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = req.email.lower()
    ip = client_ip(request)

    if await is_locked_out(db, email):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts — try again later")

    result = await db.execute(select(OrgUser).where(OrgUser.email == email))
    org_user = result.scalar_one_or_none()

    valid = org_user is not None and org_user.is_active and verify_password(req.password, org_user.password_hash)
    await record_login_attempt(db, email, success=valid, ip_address=ip)

    if not valid:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if needs_rehash(org_user.password_hash):
        org_user.password_hash = hash_password(req.password)

    await audit_service.record(
        db,
        actor_type=ActorType.org_user,
        actor_id=org_user.id,
        action="orgs.login",
        entity_type="org_user",
        entity_id=org_user.id,
        ip_address=ip,
    )
    tokens = await issue_tokens(db, audience="org", org_user_id=org_user.id)
    await db.commit()

    set_refresh_cookie(response, tokens.raw_refresh_token, tokens.refresh_expires_at_seconds, path=ORG_COOKIE_PATH)
    return schemas.OrgAccessTokenResponse(access_token=tokens.access_token, org_user=schemas.OrgUserOut.model_validate(org_user))


@client_router.post("/refresh", response_model=schemas.OrgAccessTokenResponse)
async def org_refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    rotated = await rotate_refresh_token(db, raw_token)
    if rotated is None:
        clear_refresh_cookie(response, path=ORG_COOKIE_PATH)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or expired")

    old_token, new_tokens = rotated
    if old_token.org_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an org session")

    result = await db.execute(select(OrgUser).where(OrgUser.id == old_token.org_user_id))
    org_user = result.scalar_one_or_none()
    if org_user is None or not org_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")

    await db.commit()
    set_refresh_cookie(response, new_tokens.raw_refresh_token, new_tokens.refresh_expires_at_seconds, path=ORG_COOKIE_PATH)
    return schemas.OrgAccessTokenResponse(access_token=new_tokens.access_token, org_user=schemas.OrgUserOut.model_validate(org_user))


@client_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def org_logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token:
        token_hash = hash_refresh_token(raw_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        existing = result.scalar_one_or_none()
        await revoke_refresh_token(db, raw_token)
        if existing is not None and existing.org_user_id is not None:
            await audit_service.record(
                db,
                actor_type=ActorType.org_user,
                actor_id=existing.org_user_id,
                action="orgs.logout",
                entity_type="org_user",
                entity_id=existing.org_user_id,
            )
        await db.commit()
    clear_refresh_cookie(response, path=ORG_COOKIE_PATH)


@client_router.get("/me", response_model=schemas.OrgUserOut)
async def org_me(org_user: OrgUser = Depends(get_current_org_user)):
    return org_user


# --- Org-user provisioning (owner-only) ---


@client_router.post("/staff", response_model=schemas.OrgUserOut, status_code=status.HTTP_201_CREATED)
async def create_org_staff(
    req: schemas.OrgUserCreateRequest,
    owner: OrgUser = Depends(require_org_owner),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = OrgUserRole(req.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="role must be 'owner' or 'staff'") from exc

    try:
        org_user = await services.create_org_user(
            db,
            org_id=owner.org_id,
            email=req.email,
            password=req.password,
            full_name=req.full_name,
            role=role,
            actor_type=ActorType.org_user,
            actor_id=owner.id,
        )
    except services.OrgsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return org_user


# --- Groups ---


@client_router.post("/groups", response_model=schemas.GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    req: schemas.GroupCreateRequest,
    org_user: OrgUser = Depends(get_current_org_user),
    db: AsyncSession = Depends(get_db),
):
    group = await services.create_group(
        db,
        org_id=org_user.org_id,
        actor_type=ActorType.org_user,
        actor_id=org_user.id,
        **req.model_dump(),
    )
    await db.commit()
    return group


@client_router.patch("/groups/{group_id}", response_model=schemas.GroupOut)
async def update_group(
    group_id: str,
    req: schemas.GroupUpdateRequest,
    org_user: OrgUser = Depends(get_current_org_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.get(Group, group_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Group not found")
    assert_in_org(org_user, existing.org_id)

    fields = {key: value for key, value in req.model_dump().items() if value is not None}
    try:
        group = await services.update_group(db, group_id, actor_type=ActorType.org_user, actor_id=org_user.id, **fields)
    except services.OrgsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return group


# --- Group invites ---


@client_router.post("/groups/{group_id}/invite", response_model=schemas.GroupInviteOut, status_code=status.HTTP_201_CREATED)
async def create_group_invite(
    group_id: str,
    org_user: OrgUser = Depends(get_current_org_user),
    db: AsyncSession = Depends(get_db),
):
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    assert_in_org(org_user, group.org_id)

    invite = await services.create_group_invite(
        db, org_id=org_user.org_id, group_id=group_id, actor_type=ActorType.org_user, actor_id=org_user.id
    )
    await db.commit()
    return invite
