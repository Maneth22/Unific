from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class IdentityCreate(BaseModel):
    name: str
    id_type: str  # "group" | "member"
    parent_id: str | None = None


class IdentityOut(BaseModel):
    id: str
    parent_id: str | None
    id_type: str
    name: str
    path: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MoveSubtreeRequest(BaseModel):
    new_parent_id: str


class OwnPermissionUpdate(BaseModel):
    own_registered: bool | None = None
    own_connected: bool | None = None
    own_auto_respond: bool | None = None
    own_send_on: bool | None = None
    own_can_message_scope: str | None = None
    own_can_receive_scope: str | None = None
    own_credit_cap: Decimal | None = None
    own_reply_role: str | None = None
    own_reply_tone: str | None = None
    own_reply_complexity: str | None = None
    own_reply_character: str | None = None
    own_reply_language: str | None = None
    consent_required: bool | None = None


class PermissionOut(BaseModel):
    identity_id: str
    own_registered: bool | None
    own_connected: bool | None
    own_auto_respond: bool | None
    own_send_on: bool | None
    own_can_message_scope: str | None
    own_can_receive_scope: str | None
    own_credit_cap: Decimal | None
    own_reply_role: str | None
    own_reply_tone: str | None
    own_reply_complexity: str | None
    own_reply_character: str | None
    own_reply_language: str | None
    consent_required: bool

    effective_registered: bool
    effective_connected: bool
    effective_auto_respond: bool
    effective_send_on: bool
    effective_can_message_scope: str
    effective_can_receive_scope: str
    effective_credit_cap: Decimal | None
    effective_reply_role: str
    effective_reply_tone: str
    effective_reply_complexity: str
    effective_reply_character: str
    effective_reply_language: str

    model_config = {"from_attributes": True}


class ProfileAccountOut(BaseModel):
    identity_id: str
    balance: Decimal
    updated_at: datetime

    model_config = {"from_attributes": True}


class FundRequest(BaseModel):
    amount: Decimal
    description: str = ""


class TransferRequest(BaseModel):
    to_identity_id: str
    amount: Decimal
    description: str = ""


class ConsentCreate(BaseModel):
    context: str  # "onboarding" | "record_time"
    granted: bool
    retention_period: str = ""
    data_residency: str = ""
    note: str = ""


class ConsentOut(BaseModel):
    id: str
    identity_id: str
    context: str
    granted: bool
    retention_period: str
    data_residency: str
    note: str
    granted_at: datetime

    model_config = {"from_attributes": True}


# --- Client auth ---

class ClientAccountCreate(BaseModel):
    email: str
    password: str = Field(min_length=12)
    full_name: str


class ClientLoginRequest(BaseModel):
    email: str
    password: str


class ClientOut(BaseModel):
    id: str
    email: str
    full_name: str
    identity_id: str
    is_active: bool

    model_config = {"from_attributes": True}


class ClientAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client: ClientOut


# --- AI usage ---

class AiUsageRecordOut(BaseModel):
    id: str
    room: str
    agent_name: str
    provider: str
    model: str
    action: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    estimated_cost: Decimal | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AiUsageDetailOut(BaseModel):
    identity_id: str
    call_count: int
    total_tokens: int
    total_cost: Decimal
    recent: list[AiUsageRecordOut]


# --- Client accounts overview (the client's one clear money+AI page) ---

class CommunityAccountRow(BaseModel):
    identity_id: str
    name: str
    id_type: str
    is_own: bool
    balance: Decimal


class ServiceProviderRow(BaseModel):
    name: str
    kind: str
    model: str
    status: str


class AiUsageSummaryRowClient(BaseModel):
    identity_id: str | None
    identity_name: str | None
    call_count: int
    total_tokens: int
    total_cost: Decimal


class ClientAccountsOverviewOut(BaseModel):
    community_accounts: list[CommunityAccountRow]
    service_providers: list[ServiceProviderRow]
    ai_usage: list[AiUsageSummaryRowClient]
    ai_total_tokens: int
    ai_total_cost: Decimal


# --- Community groups & invites ---

class GroupCreateRequest(BaseModel):
    name: str
    parent_id: str


class GroupInviteOut(BaseModel):
    id: str
    identity_id: str
    token: str
    invite_url: str
    is_active: bool
    created_at: datetime


class CommunityOut(BaseModel):
    id: str
    name: str
    parent_id: str | None
    is_active: bool
    created_at: datetime
    member_count: int
    invite: GroupInviteOut | None


class MemberProfileOut(BaseModel):
    identity_id: str
    email: str
    phone_number: str
    extra_info: dict
    registered_at: datetime
    registered_via: str

    model_config = {"from_attributes": True}


class CommunityMemberOut(BaseModel):
    id: str
    name: str
    is_active: bool
    created_at: datetime
    profile: MemberProfileOut | None
    conversation_id: str | None


# --- Client self-registration + admin approval ---

class ClientSignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    contact_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=12)


class ClientSignupOut(BaseModel):
    id: str
    status: str


class RegistrationRequestOut(BaseModel):
    id: str
    org_name: str
    contact_name: str
    email: str
    status: str
    rejection_reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RegistrationRejectRequest(BaseModel):
    reason: str = ""


# --- Public community-member registration ---

class PublicGroupInfoOut(BaseModel):
    group_name: str
    org_name: str


class MemberRegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = ""
    mobile_number: str = Field(min_length=1, max_length=32)
    extra_info: dict = {}


class MemberRegistrationResponse(BaseModel):
    whatsapp_url: str
    member_name: str
