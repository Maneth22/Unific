"""Shared enums and helpers used across every room's models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uuid_str() -> str:
    return str(uuid.uuid4())


class RoomName(str, enum.Enum):
    """The eight rooms. Only 1-3 are built this pass; the rest exist here
    so the calendar, the archive lockers, and room accounts can reference
    them the moment a future room is stood up, without a schema change.

    This is a tagging/scoping label only — it does not imply a per-room
    access grant. Every staff account has full access to every room (see
    `app.core.security.dependencies.require_admin`); there is no
    `RoomPermission` model any more."""

    accounts = "accounts"
    profiles = "profiles"
    meeting_room = "meeting_room"
    initial_tasking = "initial_tasking"
    specialise = "specialise"
    resources = "resources"
    assets = "assets"
    hold_data = "hold_data"
