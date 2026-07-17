"""Task 2 — Profiles room API. Staff routes are gated by `require_admin`;
client routes are gated by `require_identity_scope()`, which enforces the
ancestor-path check on every request regardless of what the client
dashboard's UI shows.

This module also mounts `public_router` — unauthenticated routes for
client (organisation) self-registration and public community-member
registration. This is the second and third place in the codebase with no
auth dependency at all (the first is the Meeting Room's inbound WhatsApp
webhook) — treat every field from these routes as untrusted input.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.client import ClientRegistrationStatus, ClientUser
from app.core.models.common import RoomName
from app.core.models.staff import RefreshToken, StaffUser
from app.core.security.cookies import CLIENT_COOKIE_PATH, REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.core.security.dependencies import client_ip, require_admin
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

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

admin = require_admin
identity_scope = require_identity_scope()


# ============================= Staff routes =============================

@router.get("/identities", response_model=list[schemas.IdentityOut])
async def list_identities(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_tree(db)


@router.post("/identities", response_model=schemas.IdentityOut, status_code=status.HTTP_201_CREATED)
async def create_identity(
    req: schemas.IdentityCreate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        id_type = IdentityType(req.id_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid id_type: {req.id_type}") from exc

    try:
        identity = await services.create_identity(
            db, name=req.name, id_type=id_type, parent_id=req.parent_id,
            actor_type=ActorType.staff, actor_id=staff.id,
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return identity


@router.get("/identities/{identity_id}", response_model=schemas.IdentityOut)
async def get_identity(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    identity = await services.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity


@router.post("/identities/{identity_id}/move", response_model=schemas.IdentityOut)
async def move_subtree(
    identity_id: str,
    req: schemas.MoveSubtreeRequest,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        identity = await services.move_subtree(db, identity_id, req.new_parent_id, staff.id)
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return identity


@router.get("/identities/{identity_id}/permission", response_model=schemas.PermissionOut)
async def get_permission(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, identity_id)
    if perm is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return perm


@router.put("/identities/{identity_id}/permission", response_model=schemas.PermissionOut)
async def update_permission(
    identity_id: str,
    req: schemas.OwnPermissionUpdate,
    staff: StaffUser = Depends(admin),
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
async def get_account(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    account = await db.get(ProfileAccount, identity_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return account


@router.post("/identities/{identity_id}/fund", response_model=schemas.ProfileAccountOut)
async def fund_account(
    identity_id: str,
    req: schemas.FundRequest,
    staff: StaffUser = Depends(admin),
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
    staff: StaffUser = Depends(admin),
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
    staff: StaffUser = Depends(admin),
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
async def list_consent(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_consent(db, identity_id)


@router.post("/identities/{identity_id}/consent", response_model=schemas.ConsentOut, status_code=status.HTTP_201_CREATED)
async def record_consent(
    identity_id: str,
    req: schemas.ConsentCreate,
    staff: StaffUser = Depends(admin),
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
async def get_identity_ai_usage(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await llm_usage_service.get_usage_for_identity(db, identity_id)


# --- Client registration requests (Admin review queue) ---

@router.get("/registration-requests", response_model=list[schemas.RegistrationRequestOut])
async def list_registration_requests(
    status_filter: str | None = None,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    parsed_status = None
    if status_filter:
        try:
            parsed_status = ClientRegistrationStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}") from exc
    return await services.list_registration_requests(db, status=parsed_status)


@router.post("/registration-requests/{request_id}/approve", response_model=schemas.ClientOut)
async def approve_registration_request(
    request_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    try:
        client = await services.approve_client_registration(db, request_id, actor_id=staff.id)
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return client


@router.post("/registration-requests/{request_id}/reject", response_model=schemas.RegistrationRequestOut)
async def reject_registration_request(
    request_id: str,
    req: schemas.RegistrationRejectRequest,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        request = await services.reject_client_registration(db, request_id, actor_id=staff.id, reason=req.reason)
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return request


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


# ==================== Client communities (the "Profiles" tab) ====================

def _invite_url(token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/register/{token}"


def _invite_out(invite) -> schemas.GroupInviteOut:
    return schemas.GroupInviteOut(
        id=invite.id,
        identity_id=invite.identity_id,
        token=invite.token,
        invite_url=_invite_url(invite.token),
        is_active=invite.is_active,
        created_at=invite.created_at,
    )


@client_router.post("/communities", response_model=schemas.CommunityOut, status_code=status.HTTP_201_CREATED)
async def client_create_community(
    req: schemas.GroupCreateRequest,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """A client builds a community group (e.g. "Sandahkal Group India")
    under their own scope. The group is opened for auto-reply on creation
    (`own_connected`/`own_auto_respond=True`) — every new Identity
    otherwise inherits `connected=False`, and the entire point of the
    public registration flow below is that a member who fills the form
    can talk to the agent immediately, with no separate manual step to
    open the group first."""
    await identity_scope(identity_id=req.parent_id, client=client, db=db)
    try:
        group = await services.create_identity(
            db, name=req.name, id_type=IdentityType.group, parent_id=req.parent_id,
            actor_type=ActorType.client, actor_id=client.id,
        )
        await services.update_own_permission(
            db, group.id, actor_type=ActorType.client, actor_id=client.id,
            own_connected=True, own_auto_respond=True,
        )
        invite = await services.create_or_rotate_group_invite(
            db, identity_id=group.id, actor_type=ActorType.client, actor_id=client.id
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return schemas.CommunityOut(
        id=group.id, name=group.name, parent_id=group.parent_id, is_active=group.is_active,
        created_at=group.created_at, member_count=0, invite=_invite_out(invite),
    )


@client_router.get("/communities", response_model=list[schemas.CommunityOut])
async def client_list_communities(client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)):
    groups = await services.list_client_groups(db, client.identity_id)
    out = []
    for group in groups:
        members = await services.list_members(db, group.id)
        invite = await services.get_active_invite(db, group.id)
        out.append(
            schemas.CommunityOut(
                id=group.id, name=group.name, parent_id=group.parent_id, is_active=group.is_active,
                created_at=group.created_at, member_count=len(members),
                invite=_invite_out(invite) if invite else None,
            )
        )
    return out


@client_router.get("/communities/{group_id}/members", response_model=list[schemas.CommunityMemberOut])
async def client_list_community_members(
    group_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    from app.meeting_room.models import Conversation, ConversationStatus

    await identity_scope(identity_id=group_id, client=client, db=db)
    members = await services.list_members(db, group_id)
    out = []
    for member in members:
        profile = await services.get_member_profile(db, member.id)
        convo_result = await db.execute(
            select(Conversation.id).where(
                Conversation.identity_id == member.id, Conversation.status == ConversationStatus.active
            )
        )
        conversation_id = convo_result.scalar_one_or_none()
        out.append(
            schemas.CommunityMemberOut(
                id=member.id, name=member.name, is_active=member.is_active, created_at=member.created_at,
                profile=schemas.MemberProfileOut.model_validate(profile) if profile else None,
                conversation_id=conversation_id,
            )
        )
    return out


@client_router.post("/communities/{group_id}/invite/regenerate", response_model=schemas.GroupInviteOut)
async def client_regenerate_invite(
    group_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    await identity_scope(identity_id=group_id, client=client, db=db)
    try:
        invite = await services.create_or_rotate_group_invite(
            db, identity_id=group_id, actor_type=ActorType.client, actor_id=client.id
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _invite_out(invite)


# ============================= Public routes =============================
# No auth dependency anywhere in this router — see the module docstring.

public_router = APIRouter(prefix="/api/profiles/public", tags=["profiles:public"])


@public_router.post("/client-signup", response_model=schemas.ClientSignupOut, status_code=status.HTTP_201_CREATED)
async def public_client_signup(req: schemas.ClientSignupRequest, db: AsyncSession = Depends(get_db)):
    try:
        request = await services.submit_client_registration(
            db, org_name=req.org_name, contact_name=req.contact_name, email=req.email, password=req.password
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return schemas.ClientSignupOut(id=request.id, status=request.status.value)


@public_router.get("/invite/{token}", response_model=schemas.PublicGroupInfoOut)
async def public_get_invite(token: str, db: AsyncSession = Depends(get_db)):
    invite = await services.get_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="This registration link is invalid or has expired")
    group = await services.get_identity(db, invite.identity_id)

    # Walk to the tree root to show the org name alongside the group name.
    root = group
    while root.parent_id is not None:
        root = await services.get_identity(db, root.parent_id)

    return schemas.PublicGroupInfoOut(group_name=group.name, org_name=root.name)


@public_router.post("/invite/{token}/register", response_model=schemas.MemberRegistrationResponse)
async def public_register_member(token: str, req: schemas.MemberRegistrationRequest, db: AsyncSession = Depends(get_db)):
    """Orchestrates across profiles + meeting_room in the router, not the
    service layer — matching the existing convention that routers, not
    services, cross room boundaries (meeting_room/router.py already calls
    into profiles.services directly; nothing in profiles.services imports
    meeting_room). Instant, no review: the member is fully active the
    moment this returns."""
    from app.meeting_room import services as meeting_room_services

    invite = await services.get_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="This registration link is invalid or has expired")

    group = await services.get_identity(db, invite.identity_id)

    try:
        identity = await services.create_identity(
            db, name=req.name, id_type=IdentityType.member, parent_id=invite.identity_id,
            actor_type=ActorType.system, actor_id=None,
        )
        await services.create_member_profile(
            db, identity_id=identity.id, email=req.email, phone_number=req.mobile_number,
            extra_info=req.extra_info, source_invite_id=invite.id,
        )
        await meeting_room_services.link_phone_number(
            db, req.mobile_number, identity.id, actor_type=ActorType.system, actor_id=None
        )
        await services.record_consent(
            db, identity.id, context=ConsentContext.onboarding, granted=True, staff_id=None,
            note="Captured via public self-registration form submission",
        )
    except services.ProfilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prefill_text = settings.whatsapp_invite_prefill_template.format(name=req.name, group_name=group.name)
    whatsapp_url = f"https://wa.me/{settings.whatsapp_agent_display_number}?text={quote(prefill_text)}"

    await db.commit()
    return schemas.MemberRegistrationResponse(whatsapp_url=whatsapp_url, member_name=req.name)
