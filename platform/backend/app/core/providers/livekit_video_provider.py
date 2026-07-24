"""LiveKit-backed video provider. Room create/delete go over LiveKit's
Room Service API (one HTTP round trip); access tokens are signed locally
(no network call) — the API key/secret never leave this process.
"""
from __future__ import annotations

from datetime import timedelta

from livekit import api as lk_api

from app.config import settings
from app.core.providers.base import ProviderError, VideoProvider


class LiveKitVideoProvider(VideoProvider):
    def __init__(self):
        self.url = settings.livekit_url
        self.api_key = settings.livekit_api_key
        self.api_secret = settings.livekit_api_secret
        if not self.url or not self.api_key or not self.api_secret:
            raise ProviderError(
                "LiveKit is not configured — set LIVEKIT_URL, LIVEKIT_API_KEY and "
                "LIVEKIT_API_SECRET, or use VIDEO_PROVIDER=mock for development."
            )

    async def create_room(self, room_name: str) -> None:
        async with lk_api.LiveKitAPI(self.url, self.api_key, self.api_secret) as client:
            try:
                await client.room.create_room(lk_api.CreateRoomRequest(name=room_name))
            except Exception as exc:  # noqa: BLE001 — provider SDK errors vary, normalize to ProviderError
                raise ProviderError(f"LiveKit room creation failed: {exc}") from exc

    async def generate_access_token(
        self, *, room_name: str, participant_identity: str, participant_name: str, ttl_seconds: int
    ) -> str:
        token = (
            lk_api.AccessToken(self.api_key, self.api_secret)
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_grants(lk_api.VideoGrants(room_join=True, room=room_name))
            .with_ttl(timedelta(seconds=ttl_seconds))
        )
        return token.to_jwt()

    async def end_room(self, room_name: str) -> None:
        async with lk_api.LiveKitAPI(self.url, self.api_key, self.api_secret) as client:
            try:
                await client.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(f"LiveKit room deletion failed: {exc}") from exc
