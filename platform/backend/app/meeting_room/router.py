"""Task 3 — Meeting Room API. The webhook is the one route in this whole
codebase not gated by staff/client auth — it's the external inbound
channel — but every message it admits still goes through
`gate_service.check_and_charge` inside the pipeline before anything
happens, so an unlinked phone number is bounced immediately.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import schemas as accounts_schemas
from app.core.models.archive import ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.client import ClientUser
from app.core.models.common import RoomName
from app.core.models.staff import StaffUser
from app.core.providers.base import ProviderError
from app.core.providers.factory import get_comms_agent, get_reply_generator, get_whatsapp_provider
from app.core.security.dependencies import require_admin
from app.core.services import archive_service, scope_service
from app.database import get_db
from app.meeting_room import schemas, services
from app.meeting_room.models import Conversation, ReportType, WhatsAppLink
from app.profiles.models import Permission
from app.profiles.security import get_current_client_user
from app.profiles.services import update_own_permission

router = APIRouter(prefix="/api/meeting-room", tags=["meeting_room"])

admin = require_admin


# --- Inbound webhook (no staff/client auth — the external channel) ---

@router.post("/webhook")
async def inbound_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()
    whatsapp_provider = get_whatsapp_provider()
    comms_agent = get_comms_agent()
    reply_generator = get_reply_generator()

    parsed = whatsapp_provider.parse_webhook(payload)
    results = []
    for inbound in parsed:
        try:
            message = await services.receive_inbound_message(
                db,
                from_phone=inbound.from_phone,
                text=inbound.text,
                provider_message_id=inbound.provider_message_id,
                comms_agent=comms_agent,
                reply_generator=reply_generator,
                whatsapp_provider=whatsapp_provider,
            )
            results.append({"status": "processed", "message_id": message.id})
        except services.Bounced as exc:
            results.append({"status": "bounced", "reason": exc.reason})
    await db.commit()
    return {"results": results}


# --- WhatsApp links ---

@router.get("/whatsapp-links", response_model=list[schemas.WhatsAppLinkOut])
async def list_links(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WhatsAppLink))
    return list(result.scalars().all())


@router.post("/whatsapp-links", response_model=schemas.WhatsAppLinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(
    req: schemas.WhatsAppLinkCreate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    link = await services.link_phone_number(
        db, req.phone_number, req.identity_id, actor_type=ActorType.staff, actor_id=staff.id
    )
    await db.commit()
    return link


# --- Conversations ---

@router.get("/conversations", response_model=list[schemas.ConversationOut])
async def list_conversations(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_conversations(db)


@router.get("/conversations/{conversation_id}", response_model=schemas.ConversationDetailOut)
async def get_conversation(conversation_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.refresh(conversation, attribute_names=["messages"])
    return conversation


@router.post("/conversations/{conversation_id}/reply", response_model=schemas.MessageOut)
async def reply_to_conversation(
    conversation_id: str,
    req: schemas.ManualReplyRequest,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        message = await services.send_manual_reply(
            db,
            conversation_id=conversation_id,
            text=req.text,
            actor_type=ActorType.staff,
            actor_id=staff.id,
            comms_agent=get_comms_agent(),
            whatsapp_provider=get_whatsapp_provider(),
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return message


@router.post("/conversations/initiate", response_model=schemas.ConversationOut, status_code=status.HTTP_201_CREATED)
async def initiate_room(
    req: schemas.InitiateRoomRequest, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    try:
        conversation = await services.initiate_comms_room(
            db,
            identity_id=req.identity_id,
            target_language=req.target_language,
            tone=req.tone,
            character_name=req.character_name,
            character_role=req.character_role,
            actor_type=ActorType.staff,
            actor_id=staff.id,
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return conversation


@router.post("/conversations/{conversation_id}/reports", response_model=schemas.ReportOut, status_code=status.HTTP_201_CREATED)
async def generate_report(
    conversation_id: str,
    req: schemas.ReportGenerateRequest,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    report_type = _parse_report_type(req.report_type)
    try:
        report = await services.generate_report(
            db,
            conversation_id=conversation_id,
            report_type=report_type,
            comms_agent=get_comms_agent(),
            actor_type=ActorType.staff,
            actor_id=staff.id,
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Report generation failed: {exc}") from exc
    await db.commit()
    return report


@router.get("/conversations/{conversation_id}/reports", response_model=list[schemas.ReportOut])
async def list_reports(conversation_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_reports(db, conversation_id)


def _parse_report_type(value: str) -> ReportType:
    try:
        return ReportType(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="report_type must be 'session_summary', 'satisfaction_analysis', or 'member_summary'",
        ) from exc


# ============================= Client routes =============================

client_router = APIRouter(prefix="/api/meeting-room/client", tags=["meeting_room:client"])


@client_router.get("/conversations", response_model=list[schemas.ConversationOut])
async def client_list_conversations(
    client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    """All conversations belonging to the client's own identity or any
    descendant of it — the same scope boundary as the Profiles client API."""
    all_ids = await scope_service.descendant_ids(db, client.identity_id, include_self=True)
    result = await db.execute(
        select(Conversation).where(Conversation.identity_id.in_(all_ids)).order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


@client_router.get("/conversations/{conversation_id}", response_model=schemas.ConversationDetailOut)
async def client_get_conversation(
    conversation_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=conversation.identity_id):
        raise HTTPException(status_code=403, detail="This conversation is outside your account's scope")
    await db.refresh(conversation, attribute_names=["messages"])
    return conversation


@client_router.post("/conversations/initiate", response_model=schemas.ConversationOut, status_code=status.HTTP_201_CREATED)
async def client_initiate_room(
    req: schemas.InitiateRoomRequest,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """The client starts (or reconfigures) a comms room with someone in
    their own subtree, handing the agent its language, tone, and character
    before the conversation begins."""
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=req.identity_id):
        raise HTTPException(status_code=403, detail="This identity is outside your account's scope")
    try:
        conversation = await services.initiate_comms_room(
            db,
            identity_id=req.identity_id,
            target_language=req.target_language,
            tone=req.tone,
            character_name=req.character_name,
            character_role=req.character_role,
            actor_type=ActorType.client,
            actor_id=client.id,
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return conversation


@client_router.post("/conversations/{conversation_id}/reply", response_model=schemas.MessageOut)
async def client_reply_to_conversation(
    conversation_id: str,
    req: schemas.ManualReplyRequest,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=conversation.identity_id):
        raise HTTPException(status_code=403, detail="This conversation is outside your account's scope")
    try:
        message = await services.send_manual_reply(
            db,
            conversation_id=conversation_id,
            text=req.text,
            actor_type=ActorType.client,
            actor_id=client.id,
            comms_agent=get_comms_agent(),
            whatsapp_provider=get_whatsapp_provider(),
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return message


@client_router.post("/conversations/{conversation_id}/reports", response_model=schemas.ReportOut, status_code=status.HTTP_201_CREATED)
async def client_generate_report(
    conversation_id: str,
    req: schemas.ReportGenerateRequest,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=conversation.identity_id):
        raise HTTPException(status_code=403, detail="This conversation is outside your account's scope")
    report_type = _parse_report_type(req.report_type)
    try:
        report = await services.generate_report(
            db,
            conversation_id=conversation_id,
            report_type=report_type,
            comms_agent=get_comms_agent(),
            actor_type=ActorType.client,
            actor_id=client.id,
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Report generation failed: {exc}") from exc
    await db.commit()
    return report


@client_router.get("/conversations/{conversation_id}/reports", response_model=list[schemas.ReportOut])
async def client_list_reports(
    conversation_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=conversation.identity_id):
        raise HTTPException(status_code=403, detail="This conversation is outside your account's scope")
    return await services.list_reports(db, conversation_id)


# --- Meetings ---

@router.get("/meetings", response_model=list[schemas.MeetingOut])
async def list_meetings(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_meetings(db)


@router.post("/meetings", response_model=schemas.MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(req: schemas.MeetingCreate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    meeting = await services.schedule_meeting(
        db,
        host_identity_id=req.host_identity_id,
        scheduled_at=req.scheduled_at,
        translate_live=req.translate_live,
        staff_id=staff.id,
        notes=req.notes,
    )
    await db.commit()
    return meeting


# --- Config Board (a view over profiles.permission's reply_* fields) ---

@router.get("/config-board/{identity_id}", response_model=schemas.ConfigBoardOut)
async def get_config_board(identity_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    perm = await db.get(Permission, identity_id)
    if perm is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return schemas.ConfigBoardOut(
        identity_id=identity_id,
        role=perm.effective_reply_role,
        tone=perm.effective_reply_tone,
        complexity=perm.effective_reply_complexity,
        character=perm.effective_reply_character,
        language=perm.effective_reply_language,
    )


@router.put("/config-board/{identity_id}", response_model=schemas.ConfigBoardOut)
async def update_config_board(
    identity_id: str,
    req: schemas.ConfigBoardUpdate,
    staff: StaffUser = Depends(admin),
    db: AsyncSession = Depends(get_db),
):
    field_map = {
        "role": "own_reply_role",
        "tone": "own_reply_tone",
        "complexity": "own_reply_complexity",
        "character": "own_reply_character",
        "language": "own_reply_language",
    }
    fields = {field_map[k]: v for k, v in req.model_dump(exclude_none=True).items()}
    perm = await update_own_permission(db, identity_id, actor_type=ActorType.staff, actor_id=staff.id, **fields)
    await db.commit()
    return schemas.ConfigBoardOut(
        identity_id=identity_id,
        role=perm.effective_reply_role,
        tone=perm.effective_reply_tone,
        complexity=perm.effective_reply_complexity,
        character=perm.effective_reply_character,
        language=perm.effective_reply_language,
    )


# --- Archive Locker (reuses the core three-shelf pattern for this room) ---

@router.get("/archive/{shelf}", response_model=list[accounts_schemas.ArchiveItemOut])
async def list_archive_shelf(shelf: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    try:
        shelf_enum = ArchiveShelf(shelf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid shelf: {shelf}") from exc
    return await archive_service.list_shelf(db, RoomName.meeting_room, shelf_enum)


@router.post("/archive", response_model=accounts_schemas.ArchiveItemOut, status_code=status.HTTP_201_CREATED)
async def create_archive_item(
    req: accounts_schemas.ArchiveItemCreate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    item = await archive_service.create_item(
        db,
        room=RoomName.meeting_room,
        title=req.title,
        actor_type=ActorType.staff,
        actor_id=staff.id,
        description=req.description,
        item_type=req.item_type,
        content=req.content,
        approved_for_auto_reply=req.approved_for_auto_reply,
    )
    await db.commit()
    return item
