"""Task 3 — Meeting Room (renamed from Communications). Reply
configuration (role/tone/complexity/character/language) deliberately
lives in `profiles.permission` (Phase C), not a separate table here —
it already has the narrowing-inheritance cascade a "Config Board" needs,
so this room's Config Board is a UI/API view over that data, not a
duplicate store. Calendar and Archive Locker are likewise reused from
`core` (see `app.core.services.calendar_service` / `archive_service`
with `room=RoomName.meeting_room`) — only room-specific business data
(conversations, messages, meetings, the phone<->identity link) lives here.
"""
from __future__ import annotations

import enum
import secrets
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class ConversationStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = {"schema": "meeting_room"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[ConversationStatus] = mapped_column(Enum(ConversationStatus, name="conversation_status"), default=ConversationStatus.active)
    # The comms-room configuration, set by whoever initiates the room.
    # "auto" target language = mirror whatever language the community
    # member writes in. Character is the persona the agent speaks as —
    # e.g. name "Jake", role "a student" — kept the same through
    # translation. Empty values fall back to the identity's effective
    # reply config from profiles.permission.
    target_language: Mapped[str] = mapped_column(String(50), default="auto")
    tone: Mapped[str] = mapped_column(String(50), default="")
    character_name: Mapped[str] = mapped_column(String(100), default="")
    character_role: Mapped[str] = mapped_column(String(200), default="")
    initiated_by_client_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class ReplyMode(str, enum.Enum):
    auto = "auto"
    manual = "manual"
    adaptive = "adaptive"


class Message(Base):
    __tablename__ = "message"
    __table_args__ = {"schema": "meeting_room"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("meeting_room.conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection, name="message_direction"), nullable=False)
    mode: Mapped[ReplyMode | None] = mapped_column(Enum(ReplyMode, name="reply_mode"), nullable=True)
    # original_text = what the sender actually wrote (community's raw
    # language inbound; client's English outbound). translated_text = the
    # cross-language rendering (English clarification inbound; community-
    # language translation outbound). final_text = what actually went over
    # WhatsApp (inbound: the raw text; outbound: the translation).
    original_text: Mapped[str] = mapped_column(Text, default="")
    detected_language: Mapped[str] = mapped_column(String(20), default="")
    translated_text: Mapped[str] = mapped_column(Text, default="")
    final_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Inbound only: the tone-analysis agent's JSON insight for the client.
    tone_analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Outbound only: short English topic tags from the translation agent.
    key_points: Mapped[list] = mapped_column(JSONB, default=list)
    sent_by_staff_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    provider_message_id: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class MeetingStatus(str, enum.Enum):
    scheduled = "scheduled"
    live = "live"
    completed = "completed"
    cancelled = "cancelled"


class Meeting(Base):
    __tablename__ = "meeting"
    __table_args__ = {"schema": "meeting_room"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    # Nullable: a staff-only meeting (meeting_kind="staff") has no
    # identity-tree node to host it — staff accounts aren't identity
    # nodes at all. Set for "client_org"/"community" meetings.
    host_identity_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    translate_live: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[MeetingStatus] = mapped_column(Enum(MeetingStatus, name="meeting_status"), default=MeetingStatus.scheduled)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    # The LiveKit room this meeting maps to. Derived from `id` at creation
    # time (`f"meeting-{id}"`) rather than a random slug — since `id` is
    # already a unique uuid, this makes collisions structurally impossible
    # with no separate uniqueness check or retry loop needed.
    room_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingParticipant(Base):
    """One row per person invited to a meeting — either a node in the
    profiles identity tree (`identity_id`: a client org, sub-group, or
    community member) or a staff account (`staff_user_id`). Staff are not
    identity-tree nodes, so they need their own column rather than being
    shoehorned into `identity_id` — the CHECK constraint below enforces
    exactly one of the two is set per row."""

    __tablename__ = "meeting_participant"
    __table_args__ = (
        CheckConstraint(
            "(identity_id IS NOT NULL) != (staff_user_id IS NOT NULL)",
            name="one_actor",
        ),
        Index(
            "uq_meeting_participant_identity",
            "meeting_id",
            "identity_id",
            unique=True,
            postgresql_where=text("identity_id IS NOT NULL"),
        ),
        Index(
            "uq_meeting_participant_staff",
            "meeting_id",
            "staff_user_id",
            unique=True,
            postgresql_where=text("staff_user_id IS NOT NULL"),
        ),
        {"schema": "meeting_room"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_room.meeting.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=True
    )
    staff_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=True
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")
    invite: Mapped["MeetingInvite | None"] = relationship(
        back_populates="participant", cascade="all, delete-orphan", uselist=False
    )


class MeetingInvite(Base):
    """A passwordless, per-participant, time-bound join link — used by
    WhatsApp-only community members (no dashboard login) and, for
    convenience, every identity-side participant. Deliberately not a
    `profiles.GroupInvite` (that model is a durable, one-active-per-
    identity community registration link with rotate-not-mutate
    semantics); a meeting invite is single-meeting, single-participant,
    and expires with the meeting, so it gets its own table rather than
    overloading GroupInvite's different lifecycle."""

    __tablename__ = "meeting_invite"
    __table_args__ = {"schema": "meeting_room"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_room.meeting.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_room.meeting_participant.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, default=lambda: secrets.token_urlsafe(24)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    participant: Mapped["MeetingParticipant"] = relationship(back_populates="invite")


class WhatsAppLink(Base):
    """Phone number <-> identity mapping. A "group" is this list plus
    1:1 conversations — the Cloud API has no native groups."""

    __tablename__ = "whatsapp_link"
    __table_args__ = {"schema": "meeting_room"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("profiles.identity.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ReportType(str, enum.Enum):
    session_summary = "session_summary"
    satisfaction_analysis = "satisfaction_analysis"
    # A community member's ongoing profile summary, distinct from a single
    # session recap — surfaced on the client dashboard's community roster
    # (see app.profiles.router's /client/communities/{id}/members).
    member_summary = "member_summary"


class SessionReport(Base):
    """A generated analysis of a conversation, stored so the client can
    revisit past reports without re-spending an LLM call. `content` is
    the agent's JSON output (see comms_prompts.SESSION_REPORT_PROMPT /
    SATISFACTION_ANALYSIS_PROMPT for the shapes)."""

    __tablename__ = "session_report"
    __table_args__ = {"schema": "meeting_room"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_room.conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType, name="report_type"), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, default=dict)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    generated_by_client_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.client_user.id", ondelete="SET NULL"), nullable=True
    )
    generated_by_staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
