from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WhatsAppLinkCreate(BaseModel):
    phone_number: str
    identity_id: str


class WhatsAppLinkOut(BaseModel):
    id: str
    phone_number: str
    identity_id: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    direction: str
    mode: str | None
    original_text: str
    detected_language: str
    translated_text: str
    final_text: str
    tone_analysis: dict
    key_points: list
    provider_message_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: str
    identity_id: str
    status: str
    target_language: str
    tone: str
    character_name: str
    character_role: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class ManualReplyRequest(BaseModel):
    text: str


class InitiateRoomRequest(BaseModel):
    identity_id: str
    target_language: str = "auto"  # "auto" mirrors whatever language the community member writes in
    tone: str = "friendly"
    character_name: str = ""  # e.g. "Jake"
    character_role: str = ""  # e.g. "a student" / "a community service worker"


class ReportGenerateRequest(BaseModel):
    report_type: str  # "session_summary" | "satisfaction_analysis"


class ReportOut(BaseModel):
    id: str
    conversation_id: str
    report_type: str
    content: dict
    message_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingCreate(BaseModel):
    # None for meeting_kind="staff" — a staff-only meeting has no
    # identity-tree node to host it.
    host_identity_id: str | None = None
    scheduled_at: datetime
    translate_live: bool = True
    notes: str = ""
    participant_identity_ids: list[str] = []
    staff_participant_ids: list[str] = []
    # "staff" | "client_org" | "community" — which picker was used; only
    # "client_org" is restricted (client-org-root identities only, never
    # an ILC/community identity). See services.schedule_meeting.
    meeting_kind: str = "community"


class MeetingOut(BaseModel):
    id: str
    host_identity_id: str | None
    scheduled_at: datetime
    translate_live: bool
    status: str
    notes: str
    room_name: str
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class MeetingParticipantOut(BaseModel):
    id: str
    identity_id: str | None
    staff_user_id: str | None
    joined_at: datetime | None
    left_at: datetime | None

    model_config = {"from_attributes": True}


class MeetingDetailOut(MeetingOut):
    participants: list[MeetingParticipantOut]
    # Staff-only view: one shareable join link per identity-side
    # participant, keyed by MeetingParticipant.id. Never populated on the
    # client/public-facing responses.
    invite_urls: dict[str, str] = {}


class ClientJoinRequest(BaseModel):
    # Defaults to the client's own root identity if omitted — set this to
    # join as a specific sub-group/member within the client's own scope.
    identity_id: str | None = None


class JoinResponse(BaseModel):
    livekit_url: str
    token: str
    room_name: str


class PublicMeetingInfoOut(BaseModel):
    meeting_id: str
    scheduled_at: datetime
    status: str
    participant_name: str


class ConfigBoardOut(BaseModel):
    identity_id: str
    role: str
    tone: str
    complexity: str
    character: str
    language: str


class ConfigBoardUpdate(BaseModel):
    role: str | None = None
    tone: str | None = None
    complexity: str | None = None
    character: str | None = None
    language: str | None = None
