"""New WhatsApp pipeline API — public member self-registration, the
org-user client dashboard, and staff/admin routes (including the admin
transparency member directory). Additive alongside
`app.meeting_room.router` (untouched, still serves the old pipeline).
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.tools import ToolSlot
from app.core.rate_limit import limiter
from app.core.security.dependencies import require_admin
from app.core.services import tools_service
from app.database import get_db
from app.orgs import services as orgs_services
from app.orgs.models import Group, Org
from app.orgs.security import assert_in_org, get_current_org_user
from app.whatsapp import schemas, services
from app.whatsapp.models import WhatsappConversation as Conversation
from app.whatsapp.orchestrator import Bounced

# ============================= Public routes =============================

public_router = APIRouter(prefix="/api/whatsapp/public", tags=["whatsapp:public"])


@public_router.get("/invite/{token}", response_model=schemas.PublicGroupInfoOut)
@limiter.limit(settings.rate_limit_webhook)
async def public_get_invite(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    invite = await orgs_services.get_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="This registration link is invalid or has expired")
    org = await db.get(Org, invite.org_id)
    group_name = None
    if invite.group_id is not None:
        group = await db.get(Group, invite.group_id)
        group_name = group.name if group is not None else None
    return schemas.PublicGroupInfoOut(org_name=org.name, group_name=group_name)


@public_router.post("/invite/{token}/register", response_model=schemas.MemberRegistrationResponse)
@limiter.limit(settings.rate_limit_webhook)
async def public_register_member(
    request: Request, token: str, req: schemas.MemberRegistrationRequest, db: AsyncSession = Depends(get_db)
):
    """Orchestrates across orgs + whatsapp in the router, not the service
    layer — matching the existing convention that routers, not services,
    cross room boundaries (see app.profiles.router.public_register_member).
    Instant, no review: the member is fully active the moment this
    returns."""
    invite = await orgs_services.get_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="This registration link is invalid or has expired")
    org = await db.get(Org, invite.org_id)

    try:
        member = await orgs_services.register_member(
            db, org_id=invite.org_id, group_id=invite.group_id, name=req.name,
            actor_type=ActorType.system, actor_id=None,
        )
        await services.link_phone_number(
            db, req.mobile_number, member.id, actor_type=ActorType.system, actor_id=None
        )
    except (orgs_services.OrgsError, services.WhatsAppError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prefill_text = settings.whatsapp_invite_prefill_template.format(name=req.name, group_name=org.name)
    whatsapp_url = f"https://wa.me/{settings.whatsapp_agent_display_number}?text={quote(prefill_text)}"

    await db.commit()
    return schemas.MemberRegistrationResponse(whatsapp_url=whatsapp_url, member_name=req.name)


# ============================= Client dashboard (org-user) =============================

client_router = APIRouter(prefix="/api/whatsapp/client", tags=["whatsapp:client"])


@client_router.get("/conversations", response_model=list[schemas.ConversationOut])
async def client_list_conversations(org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    return await services.list_conversations(db, org_id=org_user.org_id)


@client_router.get("/conversations/{conversation_id}", response_model=schemas.ConversationDetailOut)
async def client_get_conversation(
    conversation_id: str, org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)
):
    conversation = await services.get_conversation_with_messages(db, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    assert_in_org(org_user, conversation.org_id)
    return schemas.ConversationDetailOut(
        id=conversation.id, member_id=conversation.member_id, org_id=conversation.org_id,
        status=conversation.status.value, target_language=conversation.target_language, tone=conversation.tone,
        character_name=conversation.character_name, character_role=conversation.character_role,
        updated_at=conversation.updated_at,
        messages=[schemas.MessageOut.model_validate(m) for m in conversation.messages],
    )


@client_router.post("/conversations/{conversation_id}/reply", response_model=schemas.MessageOut)
async def client_manual_reply(
    conversation_id: str, req: schemas.ManualReplyRequest,
    org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db),
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    assert_in_org(org_user, conversation.org_id)

    whatsapp_provider = await tools_service.get_global_tool(db, ToolSlot.whatsapp_send)
    comms_agent = await tools_service.get_global_tool(db, ToolSlot.comms_agent)
    try:
        message = await services.send_manual_reply(
            db, conversation_id=conversation_id, text=req.text, actor_type=ActorType.org_user, actor_id=org_user.id,
            whatsapp_provider=whatsapp_provider, comms_agent=comms_agent,
        )
    except services.WhatsAppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return message


# ============================= Staff/admin routes =============================

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.get("/conversations", response_model=list[schemas.ConversationOut])
async def staff_list_conversations(staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await services.list_conversations(db)


@router.get("/member-directory", response_model=list[schemas.WhatsAppMemberDirectoryRow])
async def staff_member_directory(staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """The admin transparency endpoint: every NEW-pipeline WhatsApp
    member, their group, and their org — a flat join, trivial per the
    orgs schema's flat model. The OLD pipeline's WhatsAppLink-linked
    identities are NOT included here yet — see docs/PHASE_2_NOTES.md's
    "Admin transparency" section for the reasoning and the named Prompt 5
    fast-follow to unify both."""
    rows = await services.list_whatsapp_member_directory(db)
    return [schemas.WhatsAppMemberDirectoryRow(**row) for row in rows]


@router.post("/phone-links", response_model=schemas.PhoneLinkOut, status_code=status.HTTP_201_CREATED)
async def staff_create_phone_link(
    req: schemas.PhoneLinkCreate, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    link = await services.link_phone_number(
        db, req.phone_number, req.member_id, actor_type=ActorType.staff, actor_id=staff.id
    )
    await db.commit()
    return link
