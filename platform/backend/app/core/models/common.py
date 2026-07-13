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
    so staff_room_access, the calendar, the archive lockers, and room
    accounts can reference them the moment a future room is stood up,
    without a schema change."""

    accounts = "accounts"
    profiles = "profiles"
    meeting_room = "meeting_room"
    initial_tasking = "initial_tasking"
    specialise = "specialise"
    resources = "resources"
    assets = "assets"
    hold_data = "hold_data"


class RoomPermission(str, enum.Enum):
    """A staff member's grant level within a room they've been given access to."""

    read = "read"
    write = "write"
    admin = "admin"
