from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StaffCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class StaffCategoryOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StaffDirectoryEntryOut(BaseModel):
    """The admin's "Staff" list in the Profiles Room — deliberately
    separate from the client identity tree (see ARCHITECTURE.md's
    "clients and staff should never be confused" requirement)."""

    id: str
    email: str
    full_name: str
    tier: str
    category_id: str | None
    category_name: str | None
    is_active: bool
    created_at: datetime


class StaffDirectoryLiteOut(BaseModel):
    """Just enough for any staff member to pick a message recipient —
    not the full directory (tier/category/active), which stays admin-only."""

    id: str
    full_name: str


class StaffUpdateRequest(BaseModel):
    tier: str | None = None
    category_id: str | None = None
    is_active: bool | None = None
