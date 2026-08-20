"""Live-translation status/error reporting — the piece that was missing
before this module existed: every failure in captions.py/dubbed_audio.py/
orchestrator.py used to be `logger.exception(...)`-and-forget, with no
signal reaching any participant or persisted anywhere a later API read
could see it. This module is the one place that changes.

Two independent outputs per failure:
1. A DB write (`set_translation_error`/`set_translation_active`) so a
   plain `GET` on the meeting reflects current status even for someone
   who wasn't in the call when it happened, or who joins after a crash.
2. A best-effort LiveKit data-stream broadcast (`broadcast_translation_status`)
   so anyone already in the call finds out live, without polling.

Two topics, not one, because the raw exception text must never reach a
guest: `TRANSLATION_STATUS_TOPIC` carries a generic, detail-free message
to everyone (or just the affected speaker's audience, for a per-speaker
failure); `TRANSLATION_STATUS_DETAIL_TOPIC` carries the same plus the raw
`detail` string, sent ONLY to participants whose identity starts with
`STAFF_IDENTITY_PREFIX` — this is the only place raw exception text is
ever put on the wire at all.
"""
from __future__ import annotations

import enum
import json
import logging

from livekit import rtc

from app.database import AsyncSessionLocal
from app.meeting_room.models import Meeting

logger = logging.getLogger("live_agents.status")

TRANSLATION_STATUS_TOPIC = "lk.translation_status"
TRANSLATION_STATUS_DETAIL_TOPIC = "lk.translation_status.detail"

# How much of an exception's text is worth showing a staff member at all —
# well past any real one-line message, short enough to never make the
# bubble absurd. Applied in _clean_detail below, the one choke point both
# captions.py and dubbed_audio.py's on_error(...) calls flow through.
_MAX_DETAIL_CHARS = 240


def _clean_detail(detail: str) -> str:
    """Turns a raw `str(exc)` into something an actual human can read.
    Google API client exceptions (google.api_core.exceptions.*) put their
    one-line human message in `.args[0]`/`str(exc)`'s FIRST line, then
    append a full debug dump of the raw gRPC status proto after it
    (confirmed live: a 5-minute stream-duration error's `str(exc)` runs to
    several hundred characters of `type_url`/escaped-byte proto soup) —
    that dump is never useful to a staff member reading a status bubble,
    only the first line is. Also applies a hard length cap regardless, in
    case a future exception type doesn't follow that shape at all."""
    first_line = detail.strip().splitlines()[0] if detail.strip() else detail
    if len(first_line) > _MAX_DETAIL_CHARS:
        return first_line[:_MAX_DETAIL_CHARS].rstrip() + "…"
    return first_line

# Matches services.mint_staff_join's f"staff:{staff_id}" identity
# convention — the only reliable, already-established way to tell a
# staff participant's LiveKit identity apart from a client/guest one
# without a separate roster lookup.
STAFF_IDENTITY_PREFIX = "staff:"


class TranslationErrorScope(str, enum.Enum):
    speaker = "speaker"    # this speaker's own captions are down
    language = "language"  # this target language's dubbed audio is down
    agent = "agent"        # the whole meeting translator crashed


async def set_translation_active(meeting_id: str, active: bool) -> None:
    """Best-effort — runs from a fire-and-forget background task with no
    request-scoped DB session available, same reasoning as chat_relay.py's
    _persist_original. Never raises."""
    try:
        async with AsyncSessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None:
                return
            meeting.translation_active = active
            await db.commit()
    except Exception:
        logger.exception("failed to persist translation_active meeting_id=%s", meeting_id)


async def set_translation_error(meeting_id: str, error: str | None) -> None:
    """`error=None` clears it (a successful (re)start)."""
    try:
        async with AsyncSessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None:
                return
            meeting.translation_error = _clean_detail(error) if error else error
            await db.commit()
    except Exception:
        logger.exception("failed to persist translation_error meeting_id=%s", meeting_id)


async def broadcast_translation_status(
    room: rtc.Room, *, scope: TranslationErrorScope, subject: str | None, detail: str
) -> None:
    """Best-effort, same as every other `send_text` call site in this
    package — no connection-state precheck exists anywhere else here
    either, a disconnected room just fails the send, which is caught and
    logged, not raised. JSON payloads (matching chat_relay.py's
    convention, not captions.py's plain-text one) — the frontend needs to
    branch on `scope`/`subject` programmatically, not parse prose."""
    message = _generic_message(scope, subject)
    destination = [subject] if scope is TranslationErrorScope.speaker and subject else None
    payload = {"scope": scope.value, "subject": subject, "message": message}
    try:
        await room.local_participant.send_text(
            json.dumps(payload),
            topic=TRANSLATION_STATUS_TOPIC,
            destination_identities=destination,
        )
    except Exception:
        logger.exception("failed to broadcast translation status scope=%s subject=%s", scope.value, subject)

    staff_identities = [
        identity for identity in room.remote_participants if identity.startswith(STAFF_IDENTITY_PREFIX)
    ]
    if not staff_identities:
        return
    try:
        await room.local_participant.send_text(
            json.dumps({**payload, "detail": _clean_detail(detail)}),
            topic=TRANSLATION_STATUS_DETAIL_TOPIC,
            destination_identities=staff_identities,
        )
    except Exception:
        logger.exception("failed to broadcast translation status detail scope=%s subject=%s", scope.value, subject)


async def broadcast_translation_recovered(room: rtc.Room, *, scope: TranslationErrorScope, subject: str | None) -> None:
    """Companion to `broadcast_translation_status` — sent once a
    previously-surfaced failure (i.e. one that actually crossed the
    caller's own report threshold, see dubbed_audio.py's
    `LanguageAudioPipeline._supervise`) self-heals, so a degraded bubble
    the caller showed earlier clears itself instead of sitting there
    forever waiting for a manual dismiss. Same two-topic shape as
    `broadcast_translation_status`, distinguished by `recovered: True` in
    the payload rather than a separate topic — one handler on the
    frontend branches on it. Room-broadcast only, same division of
    responsibility as `broadcast_translation_status` — the caller is
    responsible for also clearing the DB-persisted error via
    `set_translation_error(meeting_id, None)` if it wants that "success
    clears it" contract too (orchestrator.py's on_recovered callback
    does)."""
    message = _recovered_message(scope, subject)
    destination = [subject] if scope is TranslationErrorScope.speaker and subject else None
    payload = {"scope": scope.value, "subject": subject, "message": message, "recovered": True}
    try:
        await room.local_participant.send_text(
            json.dumps(payload),
            topic=TRANSLATION_STATUS_TOPIC,
            destination_identities=destination,
        )
    except Exception:
        logger.exception("failed to broadcast translation recovery scope=%s subject=%s", scope.value, subject)

    staff_identities = [
        identity for identity in room.remote_participants if identity.startswith(STAFF_IDENTITY_PREFIX)
    ]
    if not staff_identities:
        return
    try:
        await room.local_participant.send_text(
            json.dumps(payload),
            topic=TRANSLATION_STATUS_DETAIL_TOPIC,
            destination_identities=staff_identities,
        )
    except Exception:
        logger.exception("failed to broadcast translation recovery detail scope=%s subject=%s", scope.value, subject)


def _generic_message(scope: TranslationErrorScope, subject: str | None) -> str:
    if scope is TranslationErrorScope.speaker:
        return "Your captions aren't available right now."
    if scope is TranslationErrorScope.language:
        return f"Live translated audio for {subject} isn't available right now."
    return "Live translation isn't available right now."


def _recovered_message(scope: TranslationErrorScope, subject: str | None) -> str:
    if scope is TranslationErrorScope.speaker:
        return "Your captions are back."
    if scope is TranslationErrorScope.language:
        return f"Live translated audio for {subject} is back."
    return "Live translation is back."
