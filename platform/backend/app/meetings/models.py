"""UNIFIC v2's new meetings schema — bound to `orgs.Org`/`orgs.Member`/
`orgs.OrgUser` instead of the old `profiles.Identity` tree. Additive
alongside `app.meeting_room`'s `Meeting`/`MeetingParticipant`/
`MeetingInvite` (untouched) — no dual-routing needed (unlike WhatsApp's
single webhook), since each LiveKit meeting has its own dynamically
generated `room_name` with zero physical-resource collision risk.

Classes are named `OrgMeeting`/`OrgMeetingParticipant`/`OrgMeetingInvite`
rather than bare `Meeting`/`MeetingParticipant`/`MeetingInvite` — this
codebase shares ONE declarative `Base`/class registry across every room
(the same issue Prompt 3 hit and fixed by renaming
`WhatsappConversation`/`WhatsappMessage`): reusing the old module's exact
class names would raise `sqlalchemy.exc.InvalidRequestError: Multiple
classes found for path "Meeting"` the moment both modules are imported
together. `__tablename__` stays plain (`meeting`/`meeting_participant`/
`meeting_invite`) since `schema="meetings"` already disambiguates at the
DB level; only the Python class names needed to change. Enum type names
are likewise `meetings_`-prefixed to avoid a Postgres-global collision
with `meeting_room`'s existing `meeting_status`/`meeting_invite_kind`
types (confirmed database-global, not schema-scoped).

`meeting_kind` ("staff"|"client_org"|"community") and its
`_assert_client_org_only` restriction are dropped — the flat `orgs`
schema has no ILC/client-org distinction to preserve (every `Org` is
homogeneous).
"""
from __future__ import annotations

import enum
import secrets
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.common import utcnow, uuid_str
from app.database import Base


class MeetingStatus(str, enum.Enum):
    scheduled = "scheduled"
    live = "live"
    completed = "completed"
    cancelled = "cancelled"


class OrgMeeting(Base):
    __tablename__ = "meeting"
    __table_args__ = {"schema": "meetings"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    # Nullable: a staff-internal meeting has no org to belong to.
    org_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.org.id", ondelete="CASCADE"), nullable=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    translate_live: Mapped[bool] = mapped_column(Boolean, default=True)
    translate_languages: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["en"])
    status: Mapped[MeetingStatus] = mapped_column(Enum(MeetingStatus, name="meetings_meeting_status"), default=MeetingStatus.scheduled)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by_staff_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="SET NULL"), nullable=True)
    created_by_org_user_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.org_user.id", ondelete="SET NULL"), nullable=True)
    room_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Persists what actually happened at the scheduled->live transition —
    # true only if the org was entitled AND a concurrency slot was
    # available at that moment. Never re-derived or re-checked after the
    # transition; every later read (join response, admin view) just
    # reads this column. This is the "agent phase" signal a participant's
    # client uses to know a live translator is actually working this
    # call — the visible indicator itself is a later (frontend) phase's
    # job.
    translation_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    participants: Mapped[list["OrgMeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class OrgMeetingParticipant(Base):
    __tablename__ = "meeting_participant"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN member_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN org_user_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN staff_user_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN guest_name IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="one_actor",
        ),
        Index("uq_meetings_participant_member", "meeting_id", "member_id", unique=True, postgresql_where=text("member_id IS NOT NULL")),
        Index("uq_meetings_participant_org_user", "meeting_id", "org_user_id", unique=True, postgresql_where=text("org_user_id IS NOT NULL")),
        Index("uq_meetings_participant_staff", "meeting_id", "staff_user_id", unique=True, postgresql_where=text("staff_user_id IS NOT NULL")),
        {"schema": "meetings"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.meeting.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.member.id", ondelete="CASCADE"), nullable=True)
    org_user_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.org_user.id", ondelete="CASCADE"), nullable=True)
    staff_user_id: Mapped[str | None] = mapped_column(ForeignKey("core.staff_user.id", ondelete="CASCADE"), nullable=True)
    guest_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    meeting: Mapped["OrgMeeting"] = relationship(back_populates="participants")
    invite: Mapped["OrgMeetingInvite | None"] = relationship(back_populates="participant", cascade="all, delete-orphan", uselist=False)


class MeetingInviteKind(str, enum.Enum):
    personal = "personal"
    open = "open"


class OrgMeetingInvite(Base):
    __tablename__ = "meeting_invite"
    __table_args__ = (
        Index("uq_meetings_invite_open_per_meeting", "meeting_id", unique=True, postgresql_where=text("kind = 'open'")),
        {"schema": "meetings"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.meeting.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[MeetingInviteKind] = mapped_column(
        Enum(MeetingInviteKind, name="meetings_meeting_invite_kind"), default=MeetingInviteKind.personal, nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.meeting_participant.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, default=lambda: secrets.token_urlsafe(24))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    participant: Mapped["OrgMeetingParticipant | None"] = relationship(back_populates="invite")
