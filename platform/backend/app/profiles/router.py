"""Task 2 — Profiles room API. Staff routes are gated by
`require_room_access(RoomName.profiles, ...)`; client routes are gated by
`require_identity_scope()`, which enforces the ancestor-path check on
every request regardless of what the client dashboard's UI shows.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.audit import ActorType
from app.core.models.common import RoomName, RoomPermission
from app.core.models.staff import RefreshToken, StaffUser
from app.core.security.cookies import CLIENT_COOKIE_PATH, REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.core.security.dependencies import client_ip, require_room_access
from app.core.security.password import hash_password, verify_password
from app.core.security.rate_limit import is_locked_out, record_login_attempt
from app.core.security.tokens import hash_refresh_token
from app.core.services import audit_service, llm_usage_service
from app.core.services.token_service import issue_tokens, revoke_refresh_token, rotate_refresh_token
from app.database import get_db
from app.profiles import schemas, services
from app.profiles.models import ConsentContext, Identity, IdentityType, Permission, PermissionScope, ProfileAccount
from app.profiles.security import get_current_client_user, require_identity_scope
from sqlalchemy import select

from app.core.models.client import ClientUser

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

read_access = require_room_access(RoomName.profiles, RoomPermission.read)
write_access = require_room_access(RoomName.profiles, RoomPermission.write)
identity_scope = require_identity_scope()


# ============================= Staff routes =============================

@router.get("/identities", response_model=list[schemas.IdentityOut])
async def list_identities(staff: StaffUser = Depends(read_access), db: AsyncSession = Depends(get_db)):
    return await services.list_tree(db)


@router.post("/identities", response_model=schemas.IdentityOut, status_code=status.HTTP_201_CREATED)
async def create_identity(
    req: schemas.IdentityCreate,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    try:
        id_type = IdentityType(req.id_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid id_type: {req.id_type}") from exc

    try:
        identity = await services.create_identity(db, name=req.name, id_type=id_type, parent_id=req.parent_id, staff_id=staff.id)
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return identity


@router.get("/identities/{identity_id}", response_model=schemas.IdentityOut)
async def get_identity(identity_id: str, staff: StaffUser = Depends(read_access), db: AsyncSession = Depends(get_db)):
    identity = await services.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity


@router.post("/identities/{identity_id}/move", response_model=schemas.IdentityOut)
async def move_subtree(
    identity_id: str,
    req: schemas.MoveSubtreeRequest,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    try:
        identity = await services.move_subtree(db, identity_id, req.new_parent_id, staff.id)
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return identity


@router.get("/identities/{identity_id}/permission", response_model=schemas.PermissionOut)
async def get_permission(identity_id: str, staff: StaffUser = Depends(read_access), db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, identity_id)
    if perm is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return perm


@router.put("/identities/{identity_id}/permission", response_model=schemas.PermissionOut)
async def update_permission(
    identity_id: str,
    req: schemas.OwnPermissionUpdate,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    fields = req.model_dump(exclude_none=True)
    if "own_can_message_scope" in fields:
        fields["own_can_message_scope"] = _parse_scope(fields["own_can_message_scope"])
    if "own_can_receive_scope" in fields:
        fields["own_can_receive_scope"] = _parse_scope(fields["own_can_receive_scope"])

    try:
        perm = await services.update_own_permission(
            db, identity_id, actor_type=ActorType.staff, actor_id=staff.id, **fields
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return perm


@router.get("/identities/{identity_id}/account", response_model=schemas.ProfileAccountOut)
async def get_account(identity_id: str, staff: StaffUser = Depends(read_access), db: AsyncSession = Depends(get_db)):
    account = await db.get(ProfileAccount, identity_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return account


@router.post("/identities/{identity_id}/fund", response_model=schemas.ProfileAccountOut)
async def fund_account(
    identity_id: str,
    req: schemas.FundRequest,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    try:
        account = await services.fund_identity(
            db, identity_id, req.amount, actor_type=ActorType.staff, actor_id=staff.id, description=req.description
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return account


@router.post("/identities/{identity_id}/transfer", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_credit(
    identity_id: str,
    req: schemas.TransferRequest,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    try:
        await services.transfer_credit(
            db,
            identity_id,
            req.to_identity_id,
            req.amount,
            actor_type=ActorType.staff,
            actor_id=staff.id,
            description=req.description,
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()


@router.post("/identities/{identity_id}/client-account", response_model=schemas.ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client_account(
    identity_id: str,
    req: schemas.ClientAccountCreate,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    """Provisions the client-dashboard login for a group ID. Not open
    self-registration — a staff member with Profiles write access
    creates it, same discipline as staff accounts in Task 1."""
    identity = await services.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")

    existing = await db.execute(select(ClientUser).where(ClientUser.email == req.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    client = ClientUser(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        identity_id=identity_id,
    )
    db.add(client)
    await db.flush()
    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff.id,
        action="profiles.client_account.create",
        room=RoomName.profiles,
        entity_type="client_user",
        entity_id=client.id,
        after={"email": client.email, "identity_id": identity_id},
    )
    await db.commit()
    return client


@router.get("/identities/{identity_id}/consent", response_model=list[schemas.ConsentOut])
async def list_consent(identity_id: str, staff: StaffUser = Depends(read_access), db: AsyncSession = Depends(get_db)):
    return await services.list_consent(db, identity_id)


@router.post("/identities/{identity_id}/consent", response_model=schemas.ConsentOut, status_code=status.HTTP_201_CREATED)
async def record_consent(
    identity_id: str,
    req: schemas.ConsentCreate,
    staff: StaffUser = Depends(write_access),
    db: AsyncSession = Depends(get_db),
):
    try:
        context = ConsentContext(req.context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid context: {req.context}") from exc

    record = await services.record_consent(
        db,
        identity_id,
        context=context,
        granted=req.granted,
        staff_id=staff.id,
        retention_period=req.retention_period,
        data_residency=req.data_residency,
        note=req.note,
    )
    await db.commit()
    return record


@router.get("/identities/{identity_id}/ai-usage", response_model=schemas.AiUsageDetailOut)
async def get_identity_ai_usage(identity_id: str, staff: StaffUser = Depends(read_access), db: AsyncSession = Depends(get_db)):
    return await llm_usage_service.get_usage_for_identity(db, identity_id)


def _parse_scope(value: str) -> PermissionScope:
    try:
        return PermissionScope(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {value}") from exc


# ============================= Client auth =============================

client_router = APIRouter(prefix="/api/profiles/client", tags=["profiles:client"])


@client_router.post("/login", response_model=schemas.ClientAccessTokenResponse)
async def client_login(req: schemas.ClientLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = req.email.lower()
    ip = client_ip(request)

    if await is_locked_out(db, email):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts — try again later")

    result = await db.execute(select(ClientUser).where(ClientUser.email == email))
    client = result.scalar_one_or_none()

    valid = client is not None and client.is_active and verify_password(req.password, client.password_hash)
    await record_login_attempt(db, email, success=valid, ip_address=ip)

    if not valid:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await audit_service.record(
        db,
        actor_type=ActorType.client,
        actor_id=client.id,
        action="client.login",
        room=RoomName.profiles,
        entity_type="client_user",
        entity_id=client.id,
        ip_address=ip,
    )
    tokens = await issue_tokens(db, audience="client", client_user_id=client.id)
    await db.commit()

    set_refresh_cookie(response, tokens.raw_refresh_token, tokens.refresh_expires_at_seconds, path=CLIENT_COOKIE_PATH)
    return schemas.ClientAccessTokenResponse(access_token=tokens.access_token, client=schemas.ClientOut.model_validate(client))


@client_router.post("/refresh", response_model=schemas.ClientAccessTokenResponse)
async def client_refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    rotated = await rotate_refresh_token(db, raw_token)
    if rotated is None:
        clear_refresh_cookie(response, path=CLIENT_COOKIE_PATH)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or expired")

    old_token, new_tokens = rotated
    if old_token.client_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a client session")

    result = await db.execute(select(ClientUser).where(ClientUser.id == old_token.client_user_id))
    client = result.scalar_one_or_none()
    if client is None or not client.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")

    await db.commit()
    set_refresh_cookie(response, new_tokens.raw_refresh_token, new_tokens.refresh_expires_at_seconds, path=CLIENT_COOKIE_PATH)
    return schemas.ClientAccessTokenResponse(access_token=new_tokens.access_token, client=schemas.ClientOut.model_validate(client))


@client_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def client_logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token:
        token_hash = hash_refresh_token(raw_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        existing = result.scalar_one_or_none()
        await revoke_refresh_token(db, raw_token)
        if existing is not None and existing.client_user_id is not None:
            await audit_service.record(
                db,
                actor_type=ActorType.client,
                actor_id=existing.client_user_id,
                action="client.logout",
                room=RoomName.profiles,
                entity_type="client_user",
                entity_id=existing.client_user_id,
            )
        await db.commit()
    clear_refresh_cookie(response, path=CLIENT_COOKIE_PATH)


@client_router.get("/me", response_model=schemas.ClientOut)
async def client_me(client: ClientUser = Depends(get_current_client_user)):
    return client


# ==================== Client self-service (scope-checked) ====================

@client_router.get("/identities", response_model=list[schemas.IdentityOut])
async def client_list_identities(client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)):
    """Every identity in the client's own subtree — their community, as
    they see it (root, sub-groups, members). Used for the accounts
    overview and for picking who to open a comms room with."""
    from app.core.services import scope_service

    ids = await scope_service.descendant_ids(db, client.identity_id, include_self=True)
    result = await db.execute(select(Identity).where(Identity.id.in_(ids)).order_by(Identity.path))
    return list(result.scalars().all())


@client_router.get("/accounts-overview", response_model=schemas.ClientAccountsOverviewOut)
async def client_accounts_overview(client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)):
    """One clear page of everything the client needs to see about money
    and AI spend: each community account (their subtree) with its
    balance, the AI/service provider in use, and the token dashboard
    for their own community's usage."""
    from app.config import settings as app_settings
    from app.core.services import llm_usage_service, scope_service

    ids = await scope_service.descendant_ids(db, client.identity_id, include_self=True)

    identities_result = await db.execute(select(Identity).where(Identity.id.in_(ids)).order_by(Identity.path))
    identities = list(identities_result.scalars().all())
    accounts_result = await db.execute(select(ProfileAccount).where(ProfileAccount.identity_id.in_(ids)))
    balances = {a.identity_id: a.balance for a in accounts_result.scalars().all()}

    community_accounts = [
        schemas.CommunityAccountRow(
            identity_id=i.id,
            name=i.name,
            id_type=i.id_type.value,
            is_own=(i.id == client.identity_id),
            balance=balances.get(i.id, 0),
        )
        for i in identities
    ]

    usage = await llm_usage_service.get_usage_summary(db, identity_ids=ids)
    total_tokens = sum(row["total_tokens"] for row in usage)
    total_cost = sum(row["total_cost"] for row in usage)

    providers = [
        schemas.ServiceProviderRow(
            name="Google Gemini",
            kind="AI language model",
            model=app_settings.gemini_model,
            status="active" if app_settings.gemini_api_key else "not configured",
        ),
        schemas.ServiceProviderRow(
            name="WhatsApp",
            kind="Messaging",
            model=app_settings.whatsapp_provider,
            status="active" if app_settings.whatsapp_provider == "cloud_api" else "test mode",
        ),
    ]

    return schemas.ClientAccountsOverviewOut(
        community_accounts=community_accounts,
        service_providers=providers,
        ai_usage=[schemas.AiUsageSummaryRowClient(**row) for row in usage],
        ai_total_tokens=total_tokens,
        ai_total_cost=total_cost,
    )


@client_router.get("/identities/{identity_id}", response_model=schemas.IdentityOut)
async def client_get_identity(identity_id: str, client: ClientUser = Depends(identity_scope), db: AsyncSession = Depends(get_db)):
    identity = await services.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity


@client_router.get("/identities/{identity_id}/permission", response_model=schemas.PermissionOut)
async def client_get_permission(identity_id: str, client: ClientUser = Depends(identity_scope), db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, identity_id)
    if perm is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return perm


@client_router.put("/identities/{identity_id}/permission", response_model=schemas.PermissionOut)
async def client_update_permission(
    identity_id: str,
    req: schemas.OwnPermissionUpdate,
    client: ClientUser = Depends(identity_scope),
    db: AsyncSession = Depends(get_db),
):
    """A client may configure any identity within their own scope — the
    narrowing rule is self-enforcing in the cascade regardless of who
    calls it, so this can safely reuse the same service function staff
    routes use."""
    fields = req.model_dump(exclude_none=True)
    if "own_can_message_scope" in fields:
        fields["own_can_message_scope"] = _parse_scope(fields["own_can_message_scope"])
    if "own_can_receive_scope" in fields:
        fields["own_can_receive_scope"] = _parse_scope(fields["own_can_receive_scope"])
    try:
        perm = await services.update_own_permission(
            db, identity_id, actor_type=ActorType.client, actor_id=client.id, **fields
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return perm


@client_router.get("/identities/{identity_id}/account", response_model=schemas.ProfileAccountOut)
async def client_get_account(identity_id: str, client: ClientUser = Depends(identity_scope), db: AsyncSession = Depends(get_db)):
    account = await db.get(ProfileAccount, identity_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return account


@client_router.post("/identities/{identity_id}/fund", response_model=schemas.ProfileAccountOut)
async def client_fund_account(
    identity_id: str,
    req: schemas.FundRequest,
    client: ClientUser = Depends(identity_scope),
    db: AsyncSession = Depends(get_db),
):
    """The client dashboard's "add tokens" action. This adds internal
    service credit to an identity within the client's own scope — it is
    not a payment gateway; real top-up rails (UPI etc.) sit behind this
    later without changing the ledger shape."""
    try:
        account = await services.fund_identity(
            db, identity_id, req.amount, actor_type=ActorType.client, actor_id=client.id, description=req.description
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return account


@client_router.post("/identities/{identity_id}/transfer", status_code=status.HTTP_204_NO_CONTENT)
async def client_transfer_credit(
    identity_id: str,
    req: schemas.TransferRequest,
    client: ClientUser = Depends(identity_scope),
    db: AsyncSession = Depends(get_db),
):
    # The recipient must also be within the client's own scope — both
    # ends of a trickle-down transfer are checked, not just the source.
    await identity_scope(identity_id=req.to_identity_id, client=client, db=db)
    try:
        await services.transfer_credit(
            db,
            identity_id,
            req.to_identity_id,
            req.amount,
            actor_type=ActorType.client,
            actor_id=client.id,
            description=req.description,
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
