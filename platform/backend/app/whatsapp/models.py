"""UNIFIC v2's new WhatsApp schema — bound to the flat `orgs.Member`
model instead of the old `profiles.Identity` tree. Additive alongside
`app.meeting_room`'s `Conversation`/`Message`/`WhatsAppLink` (untouched)
— see docs/adr/0003 and docs/PHASE_2_NOTES.md for the dual-routing
rationale: the inbound webhook is one physical endpoint that dispatches
to whichever pipeline owns a given phone number.

Classes are named `WhatsappConversation`/`WhatsappMessage` rather than
bare `Conversation`/`Message` — this codebase shares ONE declarative
`Base`/class registry across every room (confirmed: reusing the bare
names raised `sqlalchemy.exc.InvalidRequestError: Multiple classes found
for path "Message"` the moment both this module and
`app.meeting_room.models` were imported together, since SQLAlchemy
resolves `Mapped["Message"]`-style forward references and `order_by=`
strings against that single shared registry). Renaming here — rather
than touching `meeting_room/models.py`'s own relationships to
disambiguate — keeps the old pipeline's files completely untouched, per
this phase's additive charter. `__tablename__` stays plain (`conversation`/
`message`) since `schema="whatsapp"` already disambiguates at the DB
level; only the Python class names needed to change.

`ConversationStatus`/`MessageDirection`/`ReplyMode` are reused directly
from `app.meeting_room.models` rather than redeclared — Postgres enum
types are database-global, not schema-scoped, so redeclaring them here
under the same names would collide; importing the existing Python enum
classes is the correct way to point a new column at the same underlying
Postgres type without a second CREATE TYPE.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import utcnow, uuid_str
from app.database import Base
from app.meeting_room.models import ConversationStatus, MessageDirection, ReplyMode


class WhatsappConversation(Base):
    """1:1 per member, per the rebuild directive."""

    __tablename__ = "conversation"
    __table_args__ = {"schema": "whatsapp"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("orgs.member.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    # Denormalized — matches orgs.Member.org_id's own rationale: scope
    # checks (assert_in_org) are a single equality comparison, never a join.
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status"), default=ConversationStatus.active
    )
    target_language: Mapped[str] = mapped_column(String(50), default="auto")
    tone: Mapped[str] = mapped_column(String(50), default="")
    character_name: Mapped[str] = mapped_column(String(100), default="")
    character_role: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    messages: Mapped[list["WhatsappMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="WhatsappMessage.created_at"
    )


class WhatsappMessage(Base):
    """Append-only, high-volume — integer autoincrement PK, matching
    `meeting_room.Message`'s precedent."""

    __tablename__ = "message"
    __table_args__ = (
        # A real unique index on provider_message_id — unlike the old
        # table's un-indexed duplicate-prone column — a second, DB-level
        # idempotency backstop below the webhook's Redis-level SETNX.
        Index(
            "uq_whatsapp_message_provider_message_id",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id != ''"),
        ),
        {"schema": "whatsapp"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("whatsapp.conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection, name="message_direction"), nullable=False)
    mode: Mapped[ReplyMode | None] = mapped_column(Enum(ReplyMode, name="reply_mode"), nullable=True)
    original_text: Mapped[str] = mapped_column(Text, default="")
    detected_language: Mapped[str] = mapped_column(String(20), default="")
    translated_text: Mapped[str] = mapped_column(Text, default="")
    final_text: Mapped[str] = mapped_column(Text, nullable=False)
    tone_analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    key_points: Mapped[list] = mapped_column(JSONB, default=list)
    sent_by_org_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("orgs.org_user.id", ondelete="SET NULL"), nullable=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    conversation: Mapped["WhatsappConversation"] = relationship(back_populates="messages")


class PhoneLink(Base):
    """Phone number <-> orgs.Member mapping — the new pipeline's
    equivalent of `meeting_room.WhatsAppLink`. This is the table the
    webhook's dispatch point checks first (see app.meeting_room.router)."""

    __tablename__ = "phone_link"
    __table_args__ = {"schema": "whatsapp"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("orgs.member.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
