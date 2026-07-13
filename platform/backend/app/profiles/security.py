"""Client-dashboard auth and scoping — the counterpart to
`app.core.security.dependencies` for staff. A client is always linked to
exactly one `profiles.identity` (their root); every route that takes an
`identity_id` from the client must run it through `require_identity_scope`,
which does the same ancestor-path check the Flags & Issues doc explicitly
calls for: "test it by trying to reach another group's data with a valid
login."
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.client import ClientUser
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


def require_identity_scope():
    """Returns a dependency-factory: call it with the target identity_id
    (usually a path param) to enforce that the current client's root
    identity is that id or an ancestor of it. Enforced server-side on
    every request — never only hidden in the UI.
    """

    async def checker(
        identity_id: str,
        client: ClientUser = Depends(get_current_client_user),
        db: AsyncSession = Depends(get_db),
    ) -> ClientUser:
        if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=identity_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This identity is outside your account's scope",
            )
        return client

    return checker
