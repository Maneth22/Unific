"""Live captions, per-language dubbed audio, and translated in-call chat —
a LiveKit Agents-based subsystem embedded in this same FastAPI process
(one asyncio event loop, no separate worker), replacing the old
`app.meeting_room.live_translation` module wholesale.

See `orchestrator.py` for the full picture. This `__init__` only
re-exports the orchestration entry points and the language whitelist so
every other module in this app (`services.py`, `router.py`, `schemas.py`)
can keep importing from `app.meeting_room.live_agents` exactly the way
they used to import from `app.meeting_room.live_translation` — the
smallest-diff swap at every call site.
"""
from __future__ import annotations

from app.meeting_room.live_agents.orchestrator import start_for_meeting, stop_for_meeting
from app.meeting_room.live_agents.providers import SELECTABLE_LANGUAGES

__all__ = ["start_for_meeting", "stop_for_meeting", "SELECTABLE_LANGUAGES"]
