"""Client-dashboard auth and scoping — the counterpart to
`app.core.security.dependencies` for staff. A client is always linked to
exactly one `profiles.identity` (their root); every route that takes an
`identity_id` from the client must run it through `require_identity_scope`,
which does the same ancestor-path check the Flags & Issues doc explicitly
calls for: "test it by trying to reach another group's data with a valid
login."

Two client-side login audiences share the identity-scope mechanics:
`ClientUser` (org owner/co-owner, full access) and `ClientStaffUser`
(limited — no money/account-management routes, see `require_client_owner`).
Both carry `.identity_id`, so `require_identity_scope`/`get_current_client_actor`
treat them uniformly wherever scope is the only thing that matters (ILC
groups, members, meetings); only the owner-only routes need to
distinguish which one is calling, via `require_client_owner`.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.client import ClientStaffUser, ClientUser
from app.core.security.jwt import decode_access_token
from app.core.services import scope_service
from app.database import get_db

_bearer = HTTPBearer(auto_error=False)


async def get_current_client_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ClientUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials, audience="client")
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    client_id = payload.get("sub")
    result = await db.execute(select(ClientUser).where(ClientUser.id == client_id))
    client = result.scalar_one_or_none()
    if client is None or not client.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
    return client


async def require_client_owner(client: ClientUser = Depends(get_current_client_user)) -> ClientUser:
    """Named wrapper so owner-only routes (money, staff/co-owner
    management) read self-documenting. A `ClientStaffUser` token can't
    decode against `audience="client"` at all — see `get_current_client_user`
    — so this is enforced by audience-typing, not a role-flag check."""
    return client


async def get_current_client_staff_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ClientStaffUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials, audience="client_staff")
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    staff_id = payload.get("sub")
    result = await db.execute(select(ClientStaffUser).where(ClientStaffUser.id == staff_id))
    client_staff = result.scalar_one_or_none()
    if client_staff is None or not client_staff.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
    return client_staff


async def get_current_client_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ClientUser | ClientStaffUser:
    """Either login type, whichever the token's `aud` claim matches — for
    routes both an org owner/co-owner AND a limited client-staff account
    may use (ILC groups, members, meetings). Owner-only routes use
    `require_client_owner`/`get_current_client_user` directly instead."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials, audience="client")
    if payload is not None:
        result = await db.execute(select(ClientUser).where(ClientUser.id == payload.get("sub")))
        client = result.scalar_one_or_none()
        if client is None or not client.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
        return client

    payload = decode_access_token(credentials.credentials, audience="client_staff")
    if payload is not None:
        result = await db.execute(select(ClientStaffUser).where(ClientStaffUser.id == payload.get("sub")))
        client_staff = result.scalar_one_or_none()
        if client_staff is None or not client_staff.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
        return client_staff

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def require_identity_scope(*, owner_only: bool = False):
    """Returns a dependency-factory: call it with the target identity_id
    (usually a path param) to enforce that the current client actor's root
    identity is that id or an ancestor of it. Enforced server-side on
    every request — never only hidden in the UI.

    By default accepts either a `ClientUser` or a `ClientStaffUser` (see
    `get_current_client_actor`) — scope is purely tree-position, agnostic
    to owner-vs-staff. Pass `owner_only=True` for money routes (account
    balance, funding, transfer) — those resolve via `get_current_client_user`
    only, so a `ClientStaffUser` token (which can't decode against
    `audience="client"` at all) is rejected before scope is even checked.
    """

    async def checker(
        identity_id: str,
        client: ClientUser = Depends(get_current_client_user) if owner_only else Depends(get_current_client_actor),
        db: AsyncSession = Depends(get_db),
    ) -> ClientUser | ClientStaffUser:
        if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=identity_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This identity is outside your account's scope",
            )
        return client

    return checker
