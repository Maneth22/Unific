from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.meeting_room.live_agents import SELECTABLE_LANGUAGES

MAX_TRANSLATE_LANGUAGES = 4


def _validate_translate_languages(v: list[str]) -> list[str]:
    seen = []
    for lang in v or []:
        if lang not in seen:
            seen.append(lang)
    if "en" not in seen:
        seen.insert(0, "en")
    invalid = [lang for lang in seen if lang not in SELECTABLE_LANGUAGES]
    if invalid:
        raise ValueError(f"Unsupported language(s): {invalid}")
    return seen[:MAX_TRANSLATE_LANGUAGES]


class MeetingCreate(BaseModel):
    org_id: str | None = None
    scheduled_at: datetime
    translate_live: bool = True
    translate_languages: list[str] = Field(default_factory=lambda: ["en"])
    notes: str = ""
    participant_member_ids: list[str] | None = None
    participant_org_user_ids: list[str] | None = None

    @field_validator("translate_languages")
    @classmethod
    def _check_languages(cls, v):
        return _validate_translate_languages(v)


class ClientMeetingCreate(BaseModel):
    scheduled_at: datetime
    translate_live: bool = True
    translate_languages: list[str] = Field(default_factory=lambda: ["en"])
    notes: str = ""
    participant_member_ids: list[str] | None = None
    participant_org_user_ids: list[str] | None = None

    @field_validator("translate_languages")
    @classmethod
    def _check_languages(cls, v):
        return _validate_translate_languages(v)


class MeetingParticipantOut(BaseModel):
    id: str
    member_id: str | None
    org_user_id: str | None
    staff_user_id: str | None
    guest_name: str | None
    joined_at: datetime | None
    left_at: datetime | None

    model_config = {"from_attributes": True}


class MeetingOut(BaseModel):
    id: str
    org_id: str | None
    scheduled_at: datetime
    translate_live: bool
    translate_languages: list[str]
    status: str
    notes: str
    room_name: str
    started_at: datetime | None
    ended_at: datetime | None
    translation_active: bool

    model_config = {"from_attributes": True}


class MeetingDetailOut(MeetingOut):
    participants: list[MeetingParticipantOut]
    open_invite_url: str | None = None


class ClientJoinRequest(BaseModel):
    org_user_id: str | None = None


class AddParticipantRequest(BaseModel):
    member_id: str | None = None
    org_user_id: str | None = None
    staff_id: str | None = None


class ClientAddParticipantRequest(BaseModel):
    member_id: str | None = None


class AddParticipantResponse(BaseModel):
    participant: MeetingParticipantOut
    invite_url: str | None = None


class GuestJoinRequest(BaseModel):
    guest_name: str = Field(min_length=1, max_length=100)


class JoinResponse(BaseModel):
    livekit_url: str
    token: str
    room_name: str
    meeting_id: str
    languages: list[str] = Field(default_factory=lambda: ["en"])
    open_invite_url: str | None = None
    # The "agent phase" signal — whether a live translator is actually
    # working this call, read straight from the persisted
    # meeting.translation_active column (never re-derived per join).
    translation_active: bool = False


class PublicMeetingInfoOut(BaseModel):
    meeting_id: str
    scheduled_at: datetime
    status: str
    kind: str  # "personal" | "open"


class ActiveMeetingSessionOut(BaseModel):
    meeting_id: str
    expires_at: datetime
