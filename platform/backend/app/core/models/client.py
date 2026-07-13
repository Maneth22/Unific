"""Client (group-ID) login — the narrower counterpart to `StaffUser`.
Lives in `core` alongside `StaffUser` since both share the refresh-token
table and login-attempt machinery, but a client is always scoped to
exactly one `profiles.identity` row (their root) plus its descendants —
see `app.profiles.security.require_identity_scope`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class ClientUser(Base):
    __tablename__ = "client_user"
    __table_args__ = {"schema": "core"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
