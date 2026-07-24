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
from app.config import settings
from app.core.models.archive import ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.client import ClientUser
from app.core.models.common import RoomName
from app.core.models.staff import StaffUser
from app.core.providers.base import ProviderError
from app.core.providers.factory import get_comms_agent, get_reply_generator, get_video_provider, get_whatsapp_provider
from app.core.security.dependencies import require_admin, require_any_staff
from app.core.services import archive_service, scope_service
from app.database import get_db
from app.meeting_room import schemas, services
from app.meeting_room.models import Conversation, ReportType, WhatsAppLink
from app.tasking import services as tasking_services
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


# --- Client meetings ---

@client_router.get("/meetings", response_model=list[schemas.MeetingOut])
async def client_list_meetings(client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)):
    identity_ids = await scope_service.descendant_ids(db, client.identity_id, include_self=True)
    return await services.list_client_meetings(db, identity_ids)


@client_router.get("/meetings/{meeting_id}", response_model=schemas.MeetingOut)
async def client_get_meeting(
    meeting_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    participant_identity_ids = [p.identity_id for p in meeting.participants if p.identity_id]
    is_scoped = any(
        [
            await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=pid)
            for pid in participant_identity_ids
        ]
    )
    if not is_scoped:
        raise HTTPException(status_code=403, detail="This meeting is outside your account's scope")
    return meeting


@client_router.post("/meetings/{meeting_id}/join", response_model=schemas.JoinResponse)
async def client_join_meeting(
    meeting_id: str,
    req: schemas.ClientJoinRequest,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    target_identity_id = req.identity_id or client.identity_id
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=target_identity_id):
        raise HTTPException(status_code=403, detail="This identity is outside your account's scope")
    try:
        meeting, token = await services.mint_client_join(
            db, meeting_id=meeting_id, identity_id=target_identity_id, video_provider=get_video_provider()
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, token)


# ============================= Public routes =============================
# No auth dependency anywhere in this router — mirrors app.profiles.router's
# public_router, used here for a WhatsApp-only community member (or anyone
# else holding a valid meeting invite link) to join without a login.

public_router = APIRouter(prefix="/api/meeting-room/public", tags=["meeting_room:public"])


@public_router.get("/join/{token}", response_model=schemas.PublicMeetingInfoOut)
async def public_get_join_info(token: str, db: AsyncSession = Depends(get_db)):
    info = await services.get_public_join_info(db, token)
    if info is None:
        raise HTTPException(status_code=404, detail="This meeting link is invalid or has expired")
    meeting, _participant, identity = info
    return schemas.PublicMeetingInfoOut(
        meeting_id=meeting.id,
        scheduled_at=meeting.scheduled_at,
        status=meeting.status.value,
        participant_name=identity.name if identity is not None else "Guest",
    )


@public_router.post("/join/{token}", response_model=schemas.JoinResponse)
async def public_join_meeting(token: str, db: AsyncSession = Depends(get_db)):
    try:
        meeting, jwt_token = await services.mint_public_join(db, token=token, video_provider=get_video_provider())
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, jwt_token)


# --- Meetings ---

def _invite_url(token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/meeting-room/join/{token}"


def _join_response(meeting, token: str) -> schemas.JoinResponse:
    return schemas.JoinResponse(livekit_url=settings.livekit_url, token=token, room_name=meeting.room_name)


async def _meeting_detail_out(db: AsyncSession, meeting) -> schemas.MeetingDetailOut:
    invites = await services.get_invites_for_meeting(db, meeting.id)
    invite_urls = {inv.participant_id: _invite_url(inv.token) for inv in invites}
    return schemas.MeetingDetailOut(
        **schemas.MeetingOut.model_validate(meeting).model_dump(),
        participants=[schemas.MeetingParticipantOut.model_validate(p) for p in meeting.participants],
        invite_urls=invite_urls,
    )


@router.get("/meetings", response_model=list[schemas.MeetingOut])
async def list_meetings(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_meetings(db)


@router.get("/meetings/{meeting_id}", response_model=schemas.MeetingDetailOut)
async def get_meeting(meeting_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await _meeting_detail_out(db, meeting)


@router.post("/meetings", response_model=schemas.MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(req: schemas.MeetingCreate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    try:
        meeting = await services.schedule_meeting(
            db,
            host_identity_id=req.host_identity_id,
            scheduled_at=req.scheduled_at,
            translate_live=req.translate_live,
            staff_id=staff.id,
            notes=req.notes,
            participant_identity_ids=req.participant_identity_ids,
            staff_participant_ids=req.staff_participant_ids,
            meeting_kind=req.meeting_kind,
            video_provider=get_video_provider(),
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # "Select who gets the meeting link in their inbox" — cross-room
    # orchestration lives here in the router, not in meeting_room/services.py,
    # matching this codebase's convention that routers (not services) cross
    # room boundaries (see profiles/router.py's public registration flow).
    for staff_participant_id in req.staff_participant_ids:
        await tasking_services.send_message(
            db,
            sender_staff_id=staff.id,
            recipient_staff_id=staff_participant_id,
            subject="Meeting invitation",
            body=f"You've been invited to a meeting scheduled for {meeting.scheduled_at.isoformat()}.",
            related_meeting_id=meeting.id,
        )

    await db.commit()
    return meeting


@router.post("/meetings/{meeting_id}/join", response_model=schemas.JoinResponse)
async def join_meeting(meeting_id: str, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    """Any active staff account — admin or not — can join a meeting they
    were invited to; scheduling/managing meetings stays admin-only."""
    try:
        meeting, token = await services.mint_staff_join(
            db, meeting_id=meeting_id, staff_id=staff.id, staff_name=staff.full_name, video_provider=get_video_provider()
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, token)


@router.post("/meetings/{meeting_id}/end", response_model=schemas.MeetingOut)
async def end_meeting(meeting_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    try:
        meeting = await services.end_meeting(
            db, meeting_id=meeting_id, staff_id=staff.id, video_provider=get_video_provider()
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(meeting_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    """Force-closes the LiveKit room (so it isn't left running) and removes
    the meeting entirely — for a scheduled meeting that's no longer needed,
    or a live one that should be shut down and cleared out, not just ended."""
    try:
        await services.delete_meeting(
            db, meeting_id=meeting_id, staff_id=staff.id, video_provider=get_video_provider()
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()


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
