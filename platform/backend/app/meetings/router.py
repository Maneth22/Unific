"""New meetings API — public join, org-user client dashboard, and
staff/admin routes. Additive alongside `app.meeting_room.router`
(untouched, still serves the old pipeline's meetings).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.tools import ToolSlot
from app.core.rate_limit import limiter
from app.core.security.dependencies import require_admin, require_any_staff
from app.core.services import tools_service
from app.database import get_db
from app.meetings import schemas, services, session_store
from app.meetings.models import OrgMeeting
from app.orgs.security import assert_in_org, get_current_org_user


def _join_response(meeting: OrgMeeting, token: str) -> schemas.JoinResponse:
    return schemas.JoinResponse(
        livekit_url=settings.livekit_url, token=token, room_name=meeting.room_name, meeting_id=meeting.id,
        languages=meeting.translate_languages, translation_active=meeting.translation_active,
    )


async def _meeting_detail(db: AsyncSession, meeting: OrgMeeting) -> schemas.MeetingDetailOut:
    with_participants = await services.get_meeting_with_participants(db, meeting.id)
    open_invite = await services.get_open_invite(db, meeting.id)
    return schemas.MeetingDetailOut(
        **schemas.MeetingOut.model_validate(meeting).model_dump(),
        participants=[schemas.MeetingParticipantOut.model_validate(p) for p in (with_participants.participants if with_participants else [])],
        open_invite_url=services.build_invite_url(open_invite.token) if open_invite else None,
    )


# ============================= Public routes =============================

public_router = APIRouter(prefix="/api/meetings/public", tags=["meetings:public"])


@public_router.get("/join/{token}", response_model=schemas.PublicMeetingInfoOut)
async def public_join_info(token: str, db: AsyncSession = Depends(get_db)):
    info = await services.get_public_join_info(db, token)
    if info is None:
        raise HTTPException(status_code=404, detail="This meeting link is invalid or has expired")
    meeting, _participant, kind = info
    return schemas.PublicMeetingInfoOut(meeting_id=meeting.id, scheduled_at=meeting.scheduled_at, status=meeting.status.value, kind=kind.value)


@public_router.post("/join/{token}", response_model=schemas.JoinResponse)
async def public_join(token: str, db: AsyncSession = Depends(get_db)):
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting, jwt_token = await services.mint_public_join(db, token=token, video_provider=video_provider)
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, jwt_token)


@public_router.post("/open-join/{token}", response_model=schemas.JoinResponse)
@limiter.limit("20/minute")
async def public_open_join(request: Request, token: str, req: schemas.GuestJoinRequest, db: AsyncSession = Depends(get_db)):
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting, jwt_token = await services.redeem_open_invite(db, token=token, guest_name=req.guest_name, video_provider=video_provider)
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, jwt_token)


# ============================= Client (org) routes =============================

client_router = APIRouter(prefix="/api/meetings/client", tags=["meetings:client"])


@client_router.get("/meetings", response_model=list[schemas.MeetingOut])
async def client_list_meetings(org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    return await services.list_org_meetings(db, org_user.org_id)


@client_router.get("/meetings/{meeting_id}", response_model=schemas.MeetingDetailOut)
async def client_get_meeting(meeting_id: str, org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    assert_in_org(org_user, meeting.org_id)
    return await _meeting_detail(db, meeting)


@client_router.post("/meetings", response_model=schemas.MeetingOut, status_code=status.HTTP_201_CREATED)
async def client_schedule_meeting(req: schemas.ClientMeetingCreate, org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting = await services.schedule_meeting(
            db, org_id=org_user.org_id, scheduled_at=req.scheduled_at, translate_live=req.translate_live,
            translate_languages=req.translate_languages, org_user_id=org_user.id, notes=req.notes,
            participant_member_ids=req.participant_member_ids, participant_org_user_ids=req.participant_org_user_ids,
            video_provider=video_provider,
        )
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@client_router.post("/meetings/{meeting_id}/join", response_model=schemas.JoinResponse)
async def client_join_meeting(meeting_id: str, org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    assert_in_org(org_user, meeting.org_id)
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting, jwt_token = await services.mint_org_user_join(
            db, meeting_id=meeting_id, org_user_id=org_user.id, org_user_name=org_user.full_name, video_provider=video_provider
        )
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, jwt_token)


@client_router.post("/meetings/{meeting_id}/end", response_model=schemas.MeetingOut)
async def client_end_meeting(meeting_id: str, org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    assert_in_org(org_user, meeting.org_id)
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting = await services.end_meeting(db, meeting_id=meeting_id, video_provider=video_provider, org_user_id=org_user.id)
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@client_router.post("/meetings/{meeting_id}/participants", response_model=schemas.AddParticipantResponse, status_code=status.HTTP_201_CREATED)
async def client_add_participant(meeting_id: str, req: schemas.ClientAddParticipantRequest, org_user=Depends(get_current_org_user), db: AsyncSession = Depends(get_db)):
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    assert_in_org(org_user, meeting.org_id)
    try:
        participant, invite = await services.add_participant(
            db, meeting_id=meeting_id, member_id=req.member_id, actor_type=ActorType.org_user, actor_id=org_user.id
        )
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return schemas.AddParticipantResponse(
        participant=participant, invite_url=services.build_invite_url(invite.token) if invite else None
    )


# ============================= Staff/admin routes =============================

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.get("/meetings", response_model=list[schemas.MeetingOut])
async def staff_list_meetings(staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await services.list_meetings(db)


@router.get("/meetings/{meeting_id}", response_model=schemas.MeetingDetailOut)
async def staff_get_meeting(meeting_id: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    meeting = await db.get(OrgMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await _meeting_detail(db, meeting)


@router.post("/meetings/{meeting_id}/join", response_model=schemas.JoinResponse)
async def staff_join_meeting(meeting_id: str, staff=Depends(require_any_staff), db: AsyncSession = Depends(get_db)):
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting, jwt_token = await services.mint_staff_join(db, meeting_id=meeting_id, staff_id=staff.id, staff_name=staff.full_name, video_provider=video_provider)
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _join_response(meeting, jwt_token)


@router.post("/meetings/{meeting_id}/end", response_model=schemas.MeetingOut)
async def staff_end_meeting(meeting_id: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        meeting = await services.end_meeting(db, meeting_id=meeting_id, video_provider=video_provider, staff_id=staff.id)
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return meeting


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def staff_delete_meeting(meeting_id: str, staff=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    video_provider = await tools_service.get_global_tool(db, ToolSlot.video_provider)
    try:
        await services.delete_meeting(db, meeting_id=meeting_id, staff_id=staff.id, video_provider=video_provider)
    except services.MeetingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()


@router.get("/meetings/active-sessions", response_model=list[schemas.ActiveMeetingSessionOut])
async def staff_active_sessions(staff=Depends(require_admin)):
    """Admin visibility into the Redis concurrency registry — see
    app.meetings.session_store's module docstring for what this does and
    doesn't guarantee."""
    rows = await session_store.list_active_meetings()
    return [schemas.ActiveMeetingSessionOut(meeting_id=mid, expires_at=datetime.fromtimestamp(expires_at)) for mid, expires_at in rows]
