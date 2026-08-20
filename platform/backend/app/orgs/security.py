"""Org-dashboard auth and scoping — the `orgs.OrgUser` counterpart to
`app.core.security.dependencies` (staff) and `app.profiles.security`
(legacy client/client_staff, untouched).

Unlike the legacy split (owner vs. client-staff enforced purely by which
audience a token decoded against), `OrgUser` merges owner+staff into one
audience with a `role` column — so `require_org_owner` here is a REAL
role check, not a pass-through wrapper. There's no identity tree anymore
either, so scope enforcement is a flat `org_id` equality check
(`assert_in_org`) rather than an ancestor-path walk — called explicitly
inside route bodies after `db.get(...)`, matching this codebase's
preference for explicit checks over dependency-injection cleverness for
a check this shallow.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.jwt import decode_access_token
from app.database import get_db
from app.orgs.models import OrgUser, OrgUserRole

_bearer = HTTPBearer(auto_error=False)


async def get_current_org_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> OrgUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials, audience="org")
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    org_user_id = payload.get("sub")
    result = await db.execute(select(OrgUser).where(OrgUser.id == org_user_id))
    org_user = result.scalar_one_or_none()
    if org_user is None or not org_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
    return org_user


async def require_org_owner(org_user: OrgUser = Depends(get_current_org_user)) -> OrgUser:
    """The real security boundary for money/admin-of-org routes in the
    new system — a `role=staff` OrgUser's token decodes against the same
    "org" audience as an owner's, so this must actually inspect
    `org_user.role` (unlike legacy `require_client_owner`, which relied
    on audience-typing alone)."""
    if org_user.role != OrgUserRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
    return org_user


def assert_in_org(org_user: OrgUser, row_org_id: str) -> None:
    """The flat replacement for `app.profiles.security.
    require_identity_scope`'s ancestor-path walk — there's no tree, so
    scope is a single equality comparison. Call inline in a route body
    after `db.get(...)` loads the target row (Group/Member/etc.), passing
    that row's own `org_id`."""
    if org_user.org_id != row_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This org is outside your account's scope",
        )
