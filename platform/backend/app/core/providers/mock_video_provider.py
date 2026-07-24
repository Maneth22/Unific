"""Dev/test stand-in for LiveKit — no network calls, deterministic output,
so the full schedule/join/end flow is exercisable with zero credentials.
"""
from __future__ import annotations

from app.core.providers.base import VideoProvider


class MockVideoProvider(VideoProvider):
    async def create_room(self, room_name: str) -> None:
        return None

    async def generate_access_token(
        self, *, room_name: str, participant_identity: str, participant_name: str, ttl_seconds: int
    ) -> str:
        return f"mock-token:{room_name}:{participant_identity}"

    async def end_room(self, room_name: str) -> None:
        return None
