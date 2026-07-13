from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class StaffBootstrapRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=255)


class StaffLoginRequest(BaseModel):
    email: EmailStr
    password: str


class StaffCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=255)


class RoomAccessGrantRequest(BaseModel):
    room: str
    permission: str = "read"


class RoomAccessOut(BaseModel):
    room: str
    permission: str

    model_config = {"from_attributes": True}


class StaffOut(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_superadmin: bool
    room_access: list[RoomAccessOut] = []

    model_config = {"from_attributes": True}


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff: StaffOut
