"""Task 3 — Meeting Room API. The webhook is the one route in this whole
codebase not gated by staff/client auth — it's the external inbound
channel — but every message it admits still goes through
`gate_service.check_and_charge` inside the pipeline before anything
happens, so an unlinked phone number is bounced immediately, and every
POST body is HMAC-signature-verified (see `verify_signature`) before it's
trusted at all.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import schemas as accounts_schemas
from app.agents.whatsapp_community import orchestrator
from app.agents.whatsapp_community.flush_service import flush_all_sessions
from app.config import settings
from app.core.models.archive import ArchiveShelf
from app.core.models.audit import ActorType
from app.core.models.client import ClientUser
from app.core.models.common import RoomName
from app.core.models.staff import StaffUser
from app.core.models.webhook_log import WebhookDirection
from app.core.providers.base import ProviderError
from app.core.providers.cloud_api_whatsapp import verify_handshake, verify_signature
from app.core.rate_limit import limiter
from app.core.security.dependencies import require_admin, require_any_staff
from app.core.models.tools import ToolSlot
from app.core.services import archive_service, scope_service, tools_service, webhook_log_service
from app.database import get_db
from app.meeting_room import schemas, services
from app.meeting_room.live_agents import SELECTABLE_LANGUAGES
from app.meeting_room.models import Conversation, MeetingInviteKind, ReportType, WhatsAppLink
from app.meeting_room.phone_utils import normalize_phone
from app.tasking import services as tasking_services
from app.profiles.models import Identity, Permission
from app.profiles.security import get_current_client_user
from app.profiles.services import update_own_permission
from app.whatsapp import session_store as whatsapp_session_store
from app.whatsapp.models import PhoneLink as WhatsappPhoneLink

router = APIRouter(prefix="/api/meeting-room", tags=["meeting_room"])

admin = require_admin

WHATSAPP_PROVIDER_LOG_NAME = "whatsapp_cloud_api"


# --- Inbound webhook (no staff/client auth — the external channel) ---

@router.get("/webhook")
@limiter.limit(settings.rate_limit_webhook)
async def verify_webhook(
    request: Request,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Meta's one-time subscription-verification handshake, run whenever
    the webhook URL is (re)entered in the App Dashboard. Separate route
    from the POST event handler below — GET is verification, POST is
    events, and the two are never the same request."""
    challenge = verify_handshake(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")
    return Response(content=challenge, media_type="text/plain", status_code=status.HTTP_200_OK)


@router.post("/webhook")
@limiter.limit(settings.rate_limit_webhook)
async def inbound_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Every field here is untrusted input straight off the wire (see
    `docs/ARCHITECTURE.md`'s security boundaries) — the raw body is HMAC-
    verified against Meta's `X-Hub-Signature-256` header before it's
    trusted at all (see `verify_signature`), `CloudAPIWhatsAppProvider.
    parse_webhook` validates shape before use, and
    `orchestrator.receive_inbound_message` bounces any phone number that
    doesn't resolve to a known, linked identity before it ever reaches
    `gate_service.check_and_charge`. The raw payload is logged to
    `core.webhook_log` unconditionally — even a malformed payload, a
    rejected signature, or an unhandled downstream error still gets a row,
    which is the whole point: it's what makes debugging real Meta traffic
    possible without SSH-ing into the server to read logs."""
    raw_body = await request.body()
    if not verify_signature(
        settings.whatsapp_cloud_api_app_secret, raw_body, request.headers.get("x-hub-signature-256")
    ):
        await webhook_log_service.record(
            db,
            room=RoomName.meeting_room,
            provider=WHATSAPP_PROVIDER_LOG_NAME,
            direction=WebhookDirection.inbound,
            raw_payload={"raw": raw_body.decode("utf-8", errors="replace")},
            status="signature_invalid",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        payload = {"raw": raw_body.decode("utf-8", errors="replace")}

    status_note = "received"
    results: list[dict] = []
    error: Exception | None = None

    try:
        if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
            status_note = "invalid_object"
        else:
            whatsapp_provider = await tools_service.get_global_tool(db, ToolSlot.whatsapp_send)

            parsed = whatsapp_provider.parse_webhook(payload)
            for inbound in parsed:
                # Idempotency — shared by BOTH pipelines, checked before
                # either one ever sees the message. Fixes a real,
                # previously-existing gap (no dedup existed anywhere) in
                # one place. See app.whatsapp.session_store.
                first_seen = await whatsapp_session_store.claim_provider_message_id(
                    inbound.provider_message_id, ttl_seconds=settings.whatsapp_idempotency_ttl_seconds
                )
                if not first_seen:
                    results.append({"status": "duplicate", "provider_message_id": inbound.provider_message_id})
                    continue

                # Dual-routing dispatch point (UNIFIC v2, see
                # docs/PHASE_2_NOTES.md): a phone number found in the NEW
                # whatsapp.phone_link table goes to the new arq-based
                # pipeline; everything else falls through to the OLD
                # pipeline below, byte-for-byte unchanged.
                new_phone = normalize_phone(inbound.from_phone)
                new_link_result = await db.execute(
                    select(WhatsappPhoneLink).where(WhatsappPhoneLink.phone_number == new_phone)
                )
                if new_link_result.scalar_one_or_none() is not None:
                    await request.app.state.arq_pool.enqueue_job(
                        "process_inbound_whatsapp_message",
                        from_phone=inbound.from_phone,
                        text=inbound.text,
                        provider_message_id=inbound.provider_message_id,
                    )
                    results.append({"status": "queued", "provider_message_id": inbound.provider_message_id})
                    continue

                try:
                    # comms_agent/reply_generator are resolved INSIDE
                    # receive_inbound_message now, per the message's own
                    # identity — one webhook payload can carry messages for
                    # several distinct identities, each with its own
                    # effective Tools Registry choice; resolving once here
                    # (before the payload is even parsed) was the wrong
                    # granularity.
                    result = await orchestrator.receive_inbound_message(
                        db,
                        from_phone=inbound.from_phone,
                        text=inbound.text,
                        provider_message_id=inbound.provider_message_id,
                        whatsapp_provider=whatsapp_provider,
                    )
                    results.append({"status": "processed", "identity_id": result.identity_id})
                except orchestrator.Bounced as exc:
                    results.append({"status": "bounced", "reason": exc.reason})
            status_note = "processed" if results else "no_messages"
    except Exception as exc:  # noqa: BLE001 — the raw payload must still be logged below, then this re-raises
        error = exc
        status_note = f"error:{exc}"
        await db.rollback()  # clear the aborted transaction so the log write below can proceed

    await webhook_log_service.record(
        db,
        room=RoomName.meeting_room,
        provider=WHATSAPP_PROVIDER_LOG_NAME,
        direction=WebhookDirection.inbound,
        raw_payload=payload if isinstance(payload, dict) else {"raw": payload},
        status=status_note,
    )
    await db.commit()

    if error is not None:
        raise error
    return {"results": results}


@router.post("/admin/sessions/flush")
async def flush_sessions_now(staff: StaffUser = Depends(admin)):
    """Flushes every WhatsApp community-agent session with pending same-day
    turns from Redis into Postgres immediately, instead of waiting for the
    scheduled end-of-day job (see `app.agents.whatsapp_community.scheduler`).
    Without this, staff have no way to see "live" same-day conversations in
    the admin/client conversation viewer or in session reports until
    midnight — both read Postgres `Message` rows, which don't exist for
    today's turns until a flush happens."""
    return await flush_all_sessions()


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
    """Admin conversation viewer (Meeting Room -> Chat tab), for verifying
    the WhatsApp auto-reply pipeline actually works. identity_name is
    resolved here rather than in the service layer — it's presentation
    detail specific to this listing, not part of Conversation itself."""
    conversations = await services.list_conversations(db)
    identity_ids = {c.identity_id for c in conversations}
    names: dict[str, str] = {}
    if identity_ids:
        result = await db.execute(select(Identity.id, Identity.name).where(Identity.id.in_(identity_ids)))
        names = dict(result.all())
    return [
        schemas.ConversationOut(
            id=c.id,
            identity_id=c.identity_id,
            identity_name=names.get(c.identity_id, ""),
            status=c.status.value,
            target_language=c.target_language,
            tone=c.tone,
            character_name=c.character_name,
            character_role=c.character_role,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}", response_model=schemas.ConversationDetailOut)
async def get_conversation(conversation_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.refresh(conversation, attribute_names=["messages"])
    identity = await db.get(Identity, conversation.identity_id)
    return schemas.ConversationDetailOut(
        id=conversation.id,
        identity_id=conversation.identity_id,
        identity_name=identity.name if identity else "",
        status=conversation.status.value,
        target_language=conversation.target_language,
        tone=conversation.tone,
        character_name=conversation.character_name,
        character_role=conversation.character_role,
        updated_at=conversation.updated_at,
        messages=[schemas.MessageOut.model_validate(m) for m in conversation.messages],
    )


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
            whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send),
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
            whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send),
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

async def _assert_client_meeting_in_scope(db: AsyncSession, client: ClientUser, meeting) -> None:
    """A meeting is in a client's scope if ANY current participant is
    within their own identity subtree. Shared by client_get_meeting,
    client_end_meeting, and client_add_meeting_participant below, rather
    than each re-deriving the same check (as the first two originally
    did, independently, before this was pulled out)."""
    participant_identity_ids = [p.identity_id for p in meeting.participants if p.identity_id]
    is_scoped = any(
        [
            await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=pid)
            for pid in participant_identity_ids
        ]
    )
    if not is_scoped:
        raise HTTPException(status_code=403, detail="This meeting is outside your account's scope")


@client_router.get("/meetings", response_model=list[schemas.MeetingOut])
async def client_list_meetings(client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)):
    identity_ids = await scope_service.descendant_ids(db, client.identity_id, include_self=True)
    return await services.list_client_meetings(db, identity_ids)


@client_router.get("/meetings/{meeting_id}", response_model=schemas.MeetingDetailOut)
async def client_get_meeting(
    meeting_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    """MeetingDetailOut (not the plain MeetingOut list rows) — this is
    what actually exposes participants + personal/open invite links to
    the client scheduler; previously only the staff-only GET
    /meetings/{id} carried that shape at all, even though the invites
    themselves have always existed for client-scheduled meetings too."""
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _assert_client_meeting_in_scope(db, client, meeting)
    return await _meeting_detail_out(db, meeting)


@client_router.get("/meetings/{meeting_id}/chat", response_model=list[schemas.ChatMessageOut])
async def client_get_meeting_chat(
    meeting_id: str, client: ClientUser = Depends(get_current_client_user), db: AsyncSession = Depends(get_db)
):
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _assert_client_meeting_in_scope(db, client, meeting)
    return await services.get_meeting_chat_history(db, meeting_id)


@client_router.post("/meetings", response_model=schemas.MeetingOut, status_code=status.HTTP_201_CREATED)
async def client_schedule_meeting(
    req: schemas.ClientMeetingCreate,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """A client schedules a meeting for their own community — always
    `meeting_kind="community"` (the client-org restriction that gates the
    admin's "meet with a client" picker doesn't apply here), and every
    identity involved must be within the client's own scope."""
    all_identity_ids = {req.host_identity_id, *req.participant_identity_ids}
    for target_id in all_identity_ids:
        if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=target_id):
            raise HTTPException(status_code=403, detail="This identity is outside your account's scope")
    try:
        meeting = await services.schedule_meeting(
            db,
            host_identity_id=req.host_identity_id,
            scheduled_at=req.scheduled_at,
            translate_live=req.translate_live,
            translate_languages=req.translate_languages,
            notes=req.notes,
            participant_identity_ids=req.participant_identity_ids,
            meeting_kind="community",
            client_id=client.id,
            video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider),
            whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send),
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@client_router.post("/meetings/{meeting_id}/end", response_model=schemas.MeetingOut)
async def client_end_meeting(
    meeting_id: str,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """Closes a meeting's LiveKit room — available to any client whose
    scope covers at least one participant, mirroring `client_get_meeting`'s
    scope check rather than requiring the exact scheduler."""
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _assert_client_meeting_in_scope(db, client, meeting)
    try:
        meeting = await services.end_meeting(db, meeting_id=meeting_id, client_id=client.id, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider))
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@client_router.post("/meetings/{meeting_id}/translation/retry", response_model=schemas.MeetingOut)
async def client_retry_meeting_translation(
    meeting_id: str,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """Same scope check as `client_end_meeting` — any client whose scope
    covers at least one participant, the existing "host/client" access
    precedent for meeting-level actions."""
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _assert_client_meeting_in_scope(db, client, meeting)
    try:
        meeting = await services.retry_live_translation(
            db, meeting_id=meeting_id, actor_type=ActorType.client, actor_id=client.id
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
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
            db, meeting_id=meeting_id, identity_id=target_identity_id, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider)
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    open_invite_url = await _open_invite_url(db, meeting.id)
    return _join_response(meeting, token, open_invite_url=open_invite_url)


@client_router.post(
    "/meetings/{meeting_id}/participants", response_model=schemas.AddParticipantResponse, status_code=status.HTTP_201_CREATED
)
async def client_add_meeting_participant(
    meeting_id: str,
    req: schemas.ClientAddParticipantRequest,
    client: ClientUser = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """Adds one more identity (from the client's own subtree) to an
    already-scheduled/live meeting — the post-creation equivalent of the
    participant picker in the client scheduler's create form."""
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _assert_client_meeting_in_scope(db, client, meeting)
    if not await scope_service.is_ancestor_or_self(db, root_id=client.identity_id, target_id=req.identity_id):
        raise HTTPException(status_code=403, detail="This identity is outside your account's scope")
    try:
        participant, invite = await services.add_participant(
            db,
            meeting_id=meeting_id,
            identity_id=req.identity_id,
            actor_type=ActorType.client,
            actor_id=client.id,
            whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send),
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return schemas.AddParticipantResponse(
        participant=schemas.MeetingParticipantOut.model_validate(participant),
        invite_url=services.build_invite_url(invite.token) if invite is not None else None,
    )


# ============================= Public routes =============================
# No auth dependency anywhere in this router — mirrors app.profiles.router's
# public_router, used here for a WhatsApp-only community member (or anyone
# else holding a valid meeting invite link) to join without a login.

public_router = APIRouter(prefix="/api/meeting-room/public", tags=["meeting_room:public"])


@public_router.get("/translation-languages", response_model=list[str])
async def get_translation_languages():
    """Static config, not sensitive — unauthenticated so both the staff and
    client schedulers (and the public join page) can fetch it without an
    extra auth dependency. Single source of truth for what the scheduler's
    language picker offers, so the frontend never hardcodes/duplicates this
    list (see live_agents.providers.SELECTABLE_LANGUAGES — derived from
    settings.live_agents_stt_provider_map, so adding a language is a
    config change, not a code change)."""
    return SELECTABLE_LANGUAGES


@public_router.get("/join/{token}", response_model=schemas.PublicMeetingInfoOut)
async def public_get_join_info(token: str, db: AsyncSession = Depends(get_db)):
    """Serves both invite kinds — MeetingJoinPage.jsx branches on the
    returned `kind` to either greet a known `participant_name` (personal)
    or prompt the visitor to type their own name before joining (open,
    where participant_name is always empty since no participant exists
    yet — see services.redeem_open_invite)."""
    info = await services.get_public_join_info(db, token)
    if info is None:
        raise HTTPException(status_code=404, detail="This meeting link is invalid or has expired")
    meeting, _participant, identity, kind = info
    participant_name = "" if kind == MeetingInviteKind.open else (identity.name if identity is not None else "Guest")
    return schemas.PublicMeetingInfoOut(
        meeting_id=meeting.id,
        scheduled_at=meeting.scheduled_at,
        status=meeting.status.value,
        kind=kind.value,
        participant_name=participant_name,
    )


@public_router.get("/join/{token}/chat", response_model=list[schemas.ChatMessageOut])
async def public_get_meeting_chat(token: str, db: AsyncSession = Depends(get_db)):
    """Token-keyed, not meeting-id-keyed — reuses the exact same trust
    boundary as the join flow itself (a valid, unexpired, unrevoked
    personal or open invite for this meeting) rather than inventing a
    separate guest-auth mechanism for chat history specifically. A guest
    who joined via an open link has no other durable credential beyond
    the LiveKit connection itself, so "holds a still-valid invite link"
    is the only thing this route can reasonably check."""
    info = await services.get_public_join_info(db, token)
    if info is None:
        raise HTTPException(status_code=404, detail="This meeting link is invalid or has expired")
    meeting, _participant, _identity, _kind = info
    return await services.get_meeting_chat_history(db, meeting.id)


@public_router.post("/join/{token}", response_model=schemas.JoinResponse)
async def public_join_meeting(token: str, db: AsyncSession = Depends(get_db)):
    """Personal (kind=personal), single-recipient invite links only — see
    open_join_meeting below for the meeting-wide open-link equivalent."""
    try:
        meeting, jwt_token = await services.mint_public_join(db, token=token, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider))
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    open_invite_url = await _open_invite_url(db, meeting.id)
    return _join_response(meeting, jwt_token, open_invite_url=open_invite_url)


@public_router.post("/open-join/{token}", response_model=schemas.JoinResponse)
@limiter.limit(settings.rate_limit_open_join)
async def open_join_meeting(
    request: Request, token: str, req: schemas.GuestJoinRequest, db: AsyncSession = Depends(get_db)
):
    """Redeems the meeting's one shareable, meeting-wide open invite (see
    models.MeetingInviteKind.open / services.redeem_open_invite) — a
    separate path from the personal /join/{token} above, both so the
    frontend never has to guess which shape a token is and so this one
    can carry its own stricter rate limit (an open link is a stable,
    publicly-postable URL, e.g. dropped into a WhatsApp group) without
    also throttling personal-link joins under the same budget."""
    try:
        meeting, jwt_token = await services.redeem_open_invite(
            db, token=token, guest_name=req.guest_name, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider)
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    open_invite_url = await _open_invite_url(db, meeting.id)
    return _join_response(meeting, jwt_token, open_invite_url=open_invite_url)


# --- Meetings ---
# Invite URLs are built exclusively through services.build_invite_url —
# this router never re-derives the URL shape itself (see that function's
# docstring for why: services.py independently re-deriving the same
# string used to be a latent duplication bug).

def _join_response(meeting, token: str, *, open_invite_url: str | None = None) -> schemas.JoinResponse:
    return schemas.JoinResponse(
        livekit_url=settings.livekit_url,
        token=token,
        room_name=meeting.room_name,
        meeting_id=meeting.id,
        languages=meeting.translate_languages,
        open_invite_url=open_invite_url,
        translation_active=meeting.translation_active,
    )


async def _open_invite_url(db: AsyncSession, meeting_id: str) -> str | None:
    """Looks up the meeting's one shareable open invite and returns its
    join URL — used by every join endpoint (staff/client/public/open) so
    JoinResponse.open_invite_url lets a participant re-share the meeting
    link from inside the call (CallControlBar's "Invite" button), not
    just from a scheduler's detail view. None only for a meeting that
    predates this feature and has no open invite at all."""
    invite = await services.get_open_invite(db, meeting_id)
    return services.build_invite_url(invite.token) if invite is not None else None


async def _meeting_detail_out(db: AsyncSession, meeting) -> schemas.MeetingDetailOut:
    invites = await services.get_invites_for_meeting(db, meeting.id)
    invite_urls = {
        inv.participant_id: services.build_invite_url(inv.token)
        for inv in invites
        if inv.kind == MeetingInviteKind.personal
    }
    open_invite = next((inv for inv in invites if inv.kind == MeetingInviteKind.open), None)
    return schemas.MeetingDetailOut(
        **schemas.MeetingOut.model_validate(meeting).model_dump(),
        participants=[schemas.MeetingParticipantOut.model_validate(p) for p in meeting.participants],
        invite_urls=invite_urls,
        open_invite_url=services.build_invite_url(open_invite.token) if open_invite is not None else None,
    )


async def _meeting_staff_detail_out(db: AsyncSession, meeting) -> schemas.MeetingStaffDetailOut:
    """Staff-only counterpart to `_meeting_detail_out` — same shape plus
    the raw `translation_error`. Never called from any client-facing
    route (see MeetingStaffDetailOut's own docstring)."""
    detail = await _meeting_detail_out(db, meeting)
    return schemas.MeetingStaffDetailOut(**detail.model_dump(), translation_error=meeting.translation_error)


@router.get("/meetings", response_model=list[schemas.MeetingOut])
async def list_meetings(staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    return await services.list_meetings(db)


@router.get("/my-meetings", response_model=list[schemas.MeetingOut])
async def list_my_meetings(staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    """Any active staff account's own view — meetings they were invited to
    (or have already joined), not the full admin list. Backs the Meetings
    tab in the regular-staff portal."""
    return await services.list_staff_meetings(db, staff.id)


@router.get("/meetings/{meeting_id}", response_model=schemas.MeetingStaffDetailOut)
async def get_meeting(meeting_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await _meeting_staff_detail_out(db, meeting)


@router.get("/meetings/{meeting_id}/chat", response_model=list[schemas.ChatMessageOut])
async def get_meeting_chat(meeting_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await services.get_meeting_chat_history(db, meeting_id)


@router.post("/meetings", response_model=schemas.MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(req: schemas.MeetingCreate, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    try:
        meeting = await services.schedule_meeting(
            db,
            host_identity_id=req.host_identity_id,
            scheduled_at=req.scheduled_at,
            translate_live=req.translate_live,
            translate_languages=req.translate_languages,
            staff_id=staff.id,
            notes=req.notes,
            participant_identity_ids=req.participant_identity_ids,
            staff_participant_ids=req.staff_participant_ids,
            meeting_kind=req.meeting_kind,
            video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider),
            whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send),
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
            db, meeting_id=meeting_id, staff_id=staff.id, staff_name=staff.full_name, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider)
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    open_invite_url = await _open_invite_url(db, meeting.id)
    return _join_response(meeting, token, open_invite_url=open_invite_url)


@router.get("/my-meetings/{meeting_id}/chat", response_model=list[schemas.ChatMessageOut])
async def get_my_meeting_chat(
    meeting_id: str, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)
):
    """Regular-staff counterpart to the admin-only GET
    /meetings/{id}/chat above — same chat history, but scoped to meetings
    this staff account actually participates in (mirrors
    _assert_client_meeting_in_scope's role for the client dashboard)
    instead of requiring admin. Backs StaffMeetingsPage.jsx's in-call
    chat panel."""
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    is_participant = any(p.staff_user_id == staff.id for p in meeting.participants)
    if not is_participant:
        raise HTTPException(status_code=403, detail="This meeting is outside your account's scope")
    return await services.get_meeting_chat_history(db, meeting_id)


@router.post(
    "/meetings/{meeting_id}/participants", response_model=schemas.AddParticipantResponse, status_code=status.HTTP_201_CREATED
)
async def add_meeting_participant(
    meeting_id: str, req: schemas.AddParticipantRequest, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)
):
    """Adds one more identity or staff participant to an already-
    scheduled/live meeting — the post-creation equivalent of the
    participant picker in the create-meeting form."""
    try:
        participant, invite = await services.add_participant(
            db,
            meeting_id=meeting_id,
            identity_id=req.identity_id,
            staff_id=req.staff_user_id,
            actor_type=ActorType.staff,
            actor_id=staff.id,
            whatsapp_provider=await tools_service.get_global_tool(db, ToolSlot.whatsapp_send),
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return schemas.AddParticipantResponse(
        participant=schemas.MeetingParticipantOut.model_validate(participant),
        invite_url=services.build_invite_url(invite.token) if invite is not None else None,
    )


@router.post("/meetings/{meeting_id}/end", response_model=schemas.MeetingOut)
async def end_meeting(meeting_id: str, staff: StaffUser = Depends(admin), db: AsyncSession = Depends(get_db)):
    try:
        meeting = await services.end_meeting(
            db, meeting_id=meeting_id, staff_id=staff.id, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider)
        )
    except services.MeetingRoomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@router.post("/meetings/{meeting_id}/translation/retry", response_model=schemas.MeetingOut)
async def retry_meeting_translation(
    meeting_id: str, staff: StaffUser = Depends(require_any_staff), db: AsyncSession = Depends(get_db)
):
    """Same access shape as `get_my_meeting_chat` above — any staff
    account that's actually a participant on this meeting, not just
    admins, since it's the staff member sitting in the call who's most
    likely to be the one hitting Retry."""
    meeting = await services.get_meeting_with_participants(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    is_participant = any(p.staff_user_id == staff.id for p in meeting.participants)
    if not is_participant:
        raise HTTPException(status_code=403, detail="This meeting is outside your account's scope")
    try:
        meeting = await services.retry_live_translation(
            db, meeting_id=meeting_id, actor_type=ActorType.staff, actor_id=staff.id
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
            db, meeting_id=meeting_id, staff_id=staff.id, video_provider=await tools_service.get_global_tool(db, ToolSlot.video_provider)
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
