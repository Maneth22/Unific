"""UNIFIC v2's plugin/marketplace entitlement system — replaces the Tools
Registry's 3 meeting-room-specific slots (`meeting_stt`/`meeting_tts`/
`meeting_translation`) with a simple boolean entitlement gate. The Tools
Registry's other 4 slots (`whatsapp_send`/`reply_generator`/`comms_agent`/
`video_provider`) are UNCHANGED — see docs/PHASE_3_NOTES.md for why.

No cascading `own_*`/`effective_*` inheritance (per docs/adr/0003) — an
org either has an entitlement or it doesn't, checked with a single
indexed lookup.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow
from app.database import Base


class PluginCategory(str, enum.Enum):
    meeting_addon = "meeting_addon"
    whatsapp_agent_tier = "whatsapp_agent_tier"
    reporting = "reporting"


class EntitlementStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    cancelled = "cancelled"


class PluginCatalog(Base):
    """A purchasable capability. `key` is the stable, human-readable
    identifier every entitlement/code check references (e.g.
    "live_translation") — the primary key, not a surrogate id, since
    it's referenced by string throughout the app the same way `ToolSlot`
    values are."""

    __tablename__ = "plugin_catalog"
    __table_args__ = {"schema": "plugins"}

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[PluginCategory] = mapped_column(Enum(PluginCategory, name="plugin_category"), nullable=False)
    default_limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class OrgEntitlement(Base):
    """The join between an Org and a Plugin. Composite PK (org_id,
    plugin_key) — mirrors `core.ToolGlobalSelection`'s composite-PK
    precedent: inherently unique, no surrogate id or separate
    UniqueConstraint needed, and `entitlement_service.has` becomes a
    single PK lookup, not a filtered query."""

    __tablename__ = "org_entitlement"
    __table_args__ = {"schema": "plugins"}

    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), primary_key=True)
    plugin_key: Mapped[str] = mapped_column(
        ForeignKey("plugins.plugin_catalog.key", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[EntitlementStatus] = mapped_column(
        Enum(EntitlementStatus, name="entitlement_status"), default=EntitlementStatus.active, nullable=False
    )
    limits_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    activated_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
