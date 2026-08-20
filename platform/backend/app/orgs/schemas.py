from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


# --- Org self-registration + admin approval ---


class OrgSignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    contact_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=12)


class OrgSignupOut(BaseModel):
    id: str
    status: str


class OrgRegistrationRequestOut(BaseModel):
    id: str
    org_name: str
    contact_name: str
    email: str
    status: str
    rejection_reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgRegistrationRejectRequest(BaseModel):
    reason: str = ""


# --- Org-user auth ---


class OrgLoginRequest(BaseModel):
    email: str
    password: str


class OrgUserOut(BaseModel):
    id: str
    org_id: str
    email: str
    full_name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class OrgAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    org_user: OrgUserOut


class OrgUserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str
    role: str = "staff"  # "owner" or "staff"


# --- Org ---


class OrgOut(BaseModel):
    id: str
    name: str
    group_code: str
    entity_type: str
    role_description: str
    abn_acnc_number: str | None
    is_active: bool

    model_config = {"from_attributes": True}


# --- Groups ---


class GroupCreateRequest(BaseModel):
    name: str
    name_hindi: str = ""
    registration_number: str = ""
    date_of_registration: date | None = None
    application_signed: bool = False
    registered_office: str = ""
    area_of_operation: str = ""
    governing_act: str = ""
    registering_authority: str = ""
    objective: str = ""
    cooperative_type: str = ""
    bank_account: str = ""


class GroupUpdateRequest(BaseModel):
    name: str | None = None
    name_hindi: str | None = None
    registration_number: str | None = None
    date_of_registration: date | None = None
    application_signed: bool | None = None
    registered_office: str | None = None
    area_of_operation: str | None = None
    governing_act: str | None = None
    registering_authority: str | None = None
    objective: str | None = None
    cooperative_type: str | None = None
    bank_account: str | None = None


class GroupOut(BaseModel):
    id: str
    org_id: str
    name: str
    group_code: str
    name_hindi: str
    registration_number: str
    date_of_registration: date | None
    application_signed: bool
    registered_office: str
    area_of_operation: str
    governing_act: str
    registering_authority: str
    objective: str
    cooperative_type: str
    bank_account: str
    is_active: bool

    model_config = {"from_attributes": True}


# --- Members ---


class MemberOut(BaseModel):
    id: str
    org_id: str
    group_id: str | None
    name: str
    is_active: bool

    model_config = {"from_attributes": True}


# --- Group invites ---


class GroupInviteCreateRequest(BaseModel):
    group_id: str | None = None


class GroupInviteOut(BaseModel):
    id: str
    org_id: str
    group_id: str | None
    token: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
