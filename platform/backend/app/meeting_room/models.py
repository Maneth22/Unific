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
    # "staff" | "client_org" | "community" — which scheduler picker created
    # this meeting; only "client_org" is restricted (client-org-root
    # identities only, never an ILC/community identity — see
    # services.schedule_meeting/_assert_client_org_only). Persisted (not
    # just a schedule_meeting() parameter) so a later add_participant call
    # can re-apply the same restriction after creation.
    meeting_kind: Mapped[str] = mapped_column(String(20), default="community", nullable=False)
    translate_live: Mapped[bool] = mapped_column(Boolean, default=True)
    # A per-meeting UX scope whitelist — which languages the scheduler/join
    # UI offers for this meeting (chosen at scheduling time, validated
    # against live_agents.providers.SELECTABLE_LANGUAGES + capped at
    # schemas.MAX_TRANSLATE_LANGUAGES — see schemas.py). Not otherwise
    # consulted by live_agents itself: which STT/TTS/translate pipelines
    # actually run is driven reactively by participants' own
    # spoken_language/caption_language/audio_mode attributes, not this
    # list (see live_agents/orchestrator.py). Unused when translate_live
    # is False. Defaults to English-only for rows that predate this
    # column (migration server_default).
    translate_languages: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["en"])
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

    # Whether the live-translation agent actually started/is currently
    # running for this meeting — set at the scheduled->live transition
    # (services._mark_joined) and on every retry (services.
    # retry_live_translation), and flipped back to False by a full agent
    # crash (live_agents/status.py's set_translation_active, called from
    # orchestrator.py's _report_agent_crash). Never re-derived from
    # translate_live — a meeting can have translate_live=True and
    # translation_active=False if startup failed.
    translation_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The raw reason behind a False/degraded translation_active — staff-
    # only (see schemas.MeetingStaffDetailOut). None when translation is
    # active or was never attempted.
    translation_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            "(CASE WHEN identity_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN staff_user_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN guest_name IS NOT NULL THEN 1 ELSE 0 END) = 1",
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
    # Set only for a guest who joined via the meeting's open invite link
    # (see MeetingInviteKind.open) — no identity/staff row backs them, just
    # the name they typed in at join time. Never deduplicated against other
    # guest rows: every open-link redemption is intentionally its own row.
    guest_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")
    invite: Mapped["MeetingInvite | None"] = relationship(
        back_populates="participant", cascade="all, delete-orphan", uselist=False
    )


class MeetingInviteKind(str, enum.Enum):
    # Tied to exactly one MeetingParticipant (participant_id set) — a
    # personal, single-recipient link (identity or, historically, could be
    # extended to staff). Reusable sequentially (used_at is write-only, see
    # get_invite_by_token) but every redemption mints the SAME fixed
    # LiveKit identity, so two different people cannot hold the call
    # concurrently through one personal link.
    personal = "personal"
    # Meeting-scoped, not participant-scoped (participant_id is NULL) — the
    # one shareable "anyone with this link can join" invite per meeting.
    # Each redemption (services.redeem_open_invite) creates its own new
    # guest MeetingParticipant and mints a fresh unique LiveKit identity,
    # so many different people can use it at the same time without
    # colliding. See uq_meeting_invite_open_per_meeting below.
    open = "open"


class MeetingInvite(Base):
    """A passwordless, time-bound join link — used by WhatsApp-only
    community members (no dashboard login), for convenience by every
    identity-side participant (kind=personal), and, meeting-wide, as the
    one shareable link that lets an uninvited newcomer join (kind=open —
    see MeetingInviteKind). Deliberately not a `profiles.GroupInvite`
    (that model is a durable, one-active-per-identity community
    registration link with rotate-not-mutate semantics); a meeting invite
    is single-meeting and expires with the meeting, so it gets its own
    table rather than overloading GroupInvite's different lifecycle."""

    __tablename__ = "meeting_invite"
    __table_args__ = (
        # At most one open (meeting-wide) invite per meeting — personal
        # invites aren't constrained this way, a meeting can have many.
        Index(
            "uq_meeting_invite_open_per_meeting",
            "meeting_id",
            unique=True,
            postgresql_where=text("kind = 'open'"),
        ),
        {"schema": "meeting_room"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_room.meeting.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[MeetingInviteKind] = mapped_column(
        Enum(MeetingInviteKind, name="meeting_invite_kind"), default=MeetingInviteKind.personal, nullable=False
    )
    # NULL for kind=open (meeting-scoped, no single participant to tie it
    # to) — see MeetingInviteKind.open above.
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("meeting_room.meeting_participant.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, default=lambda: secrets.token_urlsafe(24)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    participant: Mapped["MeetingParticipant | None"] = relationship(back_populates="invite")


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


class MeetingChatMessage(Base):
    """One row per in-call chat message sent during a live meeting (see
    `app.meeting_room.live_agents.chat_relay`) — persisted so chat survives
    a page refresh/reconnect, matching this app's existing convention of
    keeping every conversation for later review (same role the WhatsApp
    `Message` model plays for the comms room). `translations` accumulates
    lazily: only the languages a live participant actually needed while
    the message was relayed (or later requested via the chat-history
    fetch) are ever computed and cached here — never every possible
    language up front."""

    __tablename__ = "meeting_chat_message"
    __table_args__ = (
        # The client-generated message_id is the natural idempotency key —
        # a retried/duplicate relay of the same message must not double-persist.
        Index("uq_meeting_chat_message_id", "meeting_id", "message_id", unique=True),
        {"schema": "meeting_room"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_room.meeting.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Raw LiveKit participant identity string (e.g. "identity:<id>",
    # "staff:<id>", "guest:<uuid>") — not a FK, mirrors how MeetingParticipant
    # already models three different identity shapes. Resolving a display
    # name from this string at read time reuses the same lookup the
    # scheduler UI already does for participants.
    sender_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_language: Mapped[str] = mapped_column(String(20), nullable=False)
    translations: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
