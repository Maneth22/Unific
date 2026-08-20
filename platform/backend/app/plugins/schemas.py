from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PluginCatalogOut(BaseModel):
    key: str
    name: str
    description: str
    category: str
    default_limits: dict
    is_active: bool

    model_config = {"from_attributes": True}


class EntitlementOut(BaseModel):
    org_id: str
    plugin_key: str
    status: str
    limits_override: dict | None
    activated_at: datetime

    model_config = {"from_attributes": True}


class CatalogToggleRequest(BaseModel):
    is_active: bool


class GrantEntitlementRequest(BaseModel):
    plugin_key: str
    limits_override: dict | None = None


class SetLimitsOverrideRequest(BaseModel):
    limits_override: dict | None = None
