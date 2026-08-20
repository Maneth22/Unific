"""General-purpose WhatsApp send endpoint, at its own top-level
`/api/whatsapp` path rather than under `/api/accounts` — kept as a second,
minimal router alongside `app.accounts.router` (which owns every other
WhatsApp route) purely because an `APIRouter`'s prefix applies to every
route mounted on it, and this endpoint's path can't live under
`/api/accounts` without changing it. Everything else — service function,
schemas, provider, auth dependency — is shared with the rest of the
WhatsApp integration; see `app.accounts.whatsapp_service.send_text`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import schemas, whatsapp_service
from app.core.models.staff import StaffUser
from app.core.models.tools import ToolSlot
from app.core.security.dependencies import require_admin
from app.core.services import tools_service
from app.database import get_db

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

admin = require_admin


@router.post("/send", response_model=schemas.WhatsAppSendOut)
async def send_whatsapp_message(
    req: schemas.WhatsAppSendRequest, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    result = await whatsapp_service.send_text(
        db, to=req.to, message=req.message, whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send)
    )
    await db.commit()
    return result
