from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# --- Public: invite lookup + member self-registration ---


class PublicGroupInfoOut(BaseModel):
    org_name: str
    group_name: str | None = None


class MemberRegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mobile_number: str = Field(min_length=1, max_length=32)


class MemberRegistrationResponse(BaseModel):
    whatsapp_url: str
    member_name: str


# --- Phone links ---


class PhoneLinkCreate(BaseModel):
    phone_number: str
    member_id: str


class PhoneLinkOut(BaseModel):
    id: str
    phone_number: str
    member_id: str

    model_config = {"from_attributes": True}


# --- Conversations / messages ---


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
    member_id: str
    org_id: str
    # Not real columns on Conversation — populated explicitly by the
    # routes that resolve them (same pattern as meeting_room.schemas.
    # ConversationOut.identity_name).
    member_name: str = ""
    org_name: str = ""
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


# --- Admin transparency ---


class WhatsAppMemberDirectoryRow(BaseModel):
    member_id: str
    member_name: str
    is_active: bool
    phone_number: str | None
    group_id: str | None
    group_name: str | None
    org_id: str
    org_name: str
