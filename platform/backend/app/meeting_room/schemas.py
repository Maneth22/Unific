from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from app.meeting_room.live_agents import SELECTABLE_LANGUAGES

# A per-meeting UX scope whitelist — which languages that meeting's
# scheduler/join UI offers at all — not a resource-provisioning cap
# anymore. The old live_translation.py needed a low cap here because each
# selected language meant a whole persistent Gemini Live session per
# speaker; the live_agents pipeline's real resource costs (STT sessions,
# TTS/queue-writer pipelines, stateless Gemini translate calls) are
# bounded independently by the three settings.live_agents_max_concurrent_*
# semaphores instead (see live_agents/orchestrator.py), so this cap only
# needs to stay a sane UX limit. Raised 3->4 to match the live_agents
# provider config's current language count (en/hi/si) plus headroom for
# the next one.
MAX_TRANSLATE_LANGUAGES = 4


def _validate_translate_languages(v: list[str]) -> list[str]:
    langs = list(dict.fromkeys(v))  # de-dup, preserve order
    if "en" not in langs:
        langs = ["en", *langs]
    invalid = [l for l in langs if l not in SELECTABLE_LANGUAGES]
    if invalid:
        raise ValueError(f"Unsupported translation language(s): {', '.join(invalid)}")
    if len(langs) > MAX_TRANSLATE_LANGUAGES:
        raise ValueError(f"At most {MAX_TRANSLATE_LANGUAGES} translation languages allowed (including English)")
    return langs


class WhatsAppLinkCreate(BaseModel):
    phone_number: str
    identity_id: str


class WhatsAppLinkOut(BaseModel):
    id: str
    phone_number: str
    identity_id: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    direction: str
    mode: str | None
    original_text: str
    detected_language: str
    translated_text: str
    final_text: str
    tone_analysis: dict
    key_points: list
    provider_message_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: str
    identity_id: str
    # Not a real column on Conversation — populated explicitly by the
    # staff list/detail routes (see router.py) for the admin conversation
    # viewer; defaults to "" everywhere else that still returns a plain
    # ORM Conversation via from_attributes (client routes, initiate).
    identity_name: str = ""
    status: str
    target_language: str
    tone: str
    character_name: str
    character_role: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class ManualReplyRequest(BaseModel):
    text: str


class InitiateRoomRequest(BaseModel):
    identity_id: str
    target_language: str = "auto"  # "auto" mirrors whatever language the community member writes in
    tone: str = "friendly"
    character_name: str = ""  # e.g. "Jake"
    character_role: str = ""  # e.g. "a student" / "a community service worker"


class ReportGenerateRequest(BaseModel):
    report_type: str  # "session_summary" | "satisfaction_analysis"


class ReportOut(BaseModel):
    id: str
    conversation_id: str
    report_type: str
    content: dict
    message_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingCreate(BaseModel):
    # None for meeting_kind="staff" — a staff-only meeting has no
    # identity-tree node to host it.
    host_identity_id: str | None = None
    scheduled_at: datetime
    translate_live: bool = True
    # Which languages to run live translation into for this meeting — English
    # is always force-included, capped at MAX_TRANSLATE_LANGUAGES, and must
    # be a subset of SELECTABLE_LANGUAGES (validated below). Ignored when
    # translate_live is False.
    translate_languages: list[str] = ["en"]
    notes: str = ""
    participant_identity_ids: list[str] = []
    staff_participant_ids: list[str] = []
    # "staff" | "client_org" | "community" — which picker was used; only
    # "client_org" is restricted (client-org-root identities only, never
    # an ILC/community identity). See services.schedule_meeting.
    meeting_kind: str = "community"

    @field_validator("translate_languages")
    @classmethod
    def _check_translate_languages(cls, v: list[str]) -> list[str]:
        return _validate_translate_languages(v)


class ClientMeetingCreate(BaseModel):
    # The community/sub-group identity to host the meeting — must be within
    # the calling client's own scope (checked server-side).
    host_identity_id: str
    scheduled_at: datetime
    translate_live: bool = True
    translate_languages: list[str] = ["en"]
    notes: str = ""
    # Other identities (also within the client's own scope) to invite —
    # e.g. additional community members alongside the host.
    participant_identity_ids: list[str] = []

    @field_validator("translate_languages")
    @classmethod
    def _check_translate_languages(cls, v: list[str]) -> list[str]:
        return _validate_translate_languages(v)


class MeetingOut(BaseModel):
    id: str
    host_identity_id: str | None
    scheduled_at: datetime
    # "staff" | "client_org" | "community" — see services.schedule_meeting.
    meeting_kind: str = "community"
    translate_live: bool
    translate_languages: list[str]
    status: str
    notes: str
    room_name: str
    started_at: datetime | None
    ended_at: datetime | None
    # Whether the live-translation agent actually started/is running for
    # this meeting — public-safe (no detail about *why* it isn't), see
    # live_agents/status.py. False for a meeting that never had
    # translate_live at all, not just one where it failed.
    translation_active: bool = False

    model_config = {"from_attributes": True}


class MeetingParticipantOut(BaseModel):
    id: str
    identity_id: str | None
    staff_user_id: str | None
    # Set only for a guest who joined via the meeting's open invite link
    # (see models.MeetingInviteKind.open) — no identity/staff record backs
    # them, just the name they typed in at join time.
    guest_name: str | None = None
    joined_at: datetime | None
    left_at: datetime | None

    model_config = {"from_attributes": True}


class MeetingDetailOut(MeetingOut):
    participants: list[MeetingParticipantOut]
    # One shareable join link per identity-side participant, keyed by
    # MeetingParticipant.id. Available on both the staff and client
    # meeting-detail responses (never on the fully public ones).
    invite_urls: dict[str, str] = {}
    # The meeting's one shareable "anyone with this link can join" invite
    # — same audience as invite_urls above (staff/client detail views),
    # None only if the meeting predates this feature and somehow has no
    # open invite yet.
    open_invite_url: str | None = None


class MeetingStaffDetailOut(MeetingDetailOut):
    """Staff-only — adds the raw failure reason behind a False/degraded
    `translation_active`. Deliberately NOT on the shared `MeetingDetailOut`
    (used by both staff's and the client dashboard's meeting-detail
    routes) — a raw exception string must never reach a client response,
    see live_agents/status.py's own staff-only detail-topic split for the
    same boundary applied to the live in-call signal."""

    translation_error: str | None = None


class ClientJoinRequest(BaseModel):
    # Defaults to the client's own root identity if omitted — set this to
    # join as a specific sub-group/member within the client's own scope.
    identity_id: str | None = None


class AddParticipantRequest(BaseModel):
    """Staff "add participant" request — exactly one of identity_id
    (an existing profiles-tree identity) or staff_user_id (another staff
    account) must be set, mirroring MeetingParticipant's own one_actor
    constraint (services.add_participant only ever sets one of the two
    itself, but this keeps a malformed request from reaching it at all)."""

    identity_id: str | None = None
    staff_user_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.identity_id is None) == (self.staff_user_id is None):
            raise ValueError("Exactly one of identity_id or staff_user_id must be set")
        return self


class ClientAddParticipantRequest(BaseModel):
    # Client-scheduled meetings never take a staff_user_id here — a client
    # can only add identities within their own scope (checked server-side).
    identity_id: str


class AddParticipantResponse(BaseModel):
    participant: MeetingParticipantOut
    # None for a staff participant (staff never get a personal invite —
    # see services.add_participant), or if the identity has no linked
    # WhatsApp number to notify (the link still exists, just not auto-sent).
    invite_url: str | None = None


class GuestJoinRequest(BaseModel):
    guest_name: str

    @field_validator("guest_name")
    @classmethod
    def _clean_guest_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("guest_name is required")
        return v[:100]


class JoinResponse(BaseModel):
    livekit_url: str
    token: str
    room_name: str
    # Lets the call UI (ChatPanel.jsx) fetch this meeting's persisted chat
    # history without the caller having to track it separately from `call`.
    meeting_id: str
    # The meeting's own translate_languages — lets the call UI restrict its
    # language picker (pre-join screen + in-call dropdown) to only the
    # languages actually running for this meeting, instead of a fixed list.
    languages: list[str] = ["en"]
    # The meeting's shareable open-invite link, if it has one — lets a
    # participant re-share it from inside the call (CallControlBar's
    # "Invite" button), not just from the scheduler UI.
    open_invite_url: str | None = None
    # Lets the call UI render the Translator participant's initial state
    # before any lk.translation_status message arrives (or at all, for a
    # meeting where translate_live is False). See MeetingOut's own field.
    translation_active: bool = False


class PublicMeetingInfoOut(BaseModel):
    meeting_id: str
    scheduled_at: datetime
    status: str
    # "personal" | "open" — tells MeetingJoinPage.jsx whether to greet a
    # known participant_name (personal) or ask the visitor to type their
    # own name before joining (open — see GuestJoinRequest).
    kind: str = "personal"
    # Empty for kind="open" — an open link doesn't know who's about to
    # join until they type a name at join time.
    participant_name: str = ""


class ConfigBoardOut(BaseModel):
    identity_id: str
    role: str
    tone: str
    complexity: str
    character: str
    language: str


class ConfigBoardUpdate(BaseModel):
    role: str | None = None
    tone: str | None = None
    complexity: str | None = None
    character: str | None = None
    language: str | None = None


class ChatMessageOut(BaseModel):
    """One persisted in-call chat message (see
    models.MeetingChatMessage / live_agents.chat_relay). `translations`
    carries every language a live participant actually needed while the
    message was relayed — never every possible language up front — so the
    client picks out its own `chat_language` (falling back to
    `original_text` if that language isn't in the dict yet) rather than
    the server pre-resolving "the" translation for a specific reader."""

    id: str
    message_id: str
    sender_identity: str
    original_text: str
    source_language: str
    translations: dict[str, str]
    created_at: datetime

    model_config = {"from_attributes": True}
