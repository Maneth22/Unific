"""Dev-only WhatsApp provider. Logs sends instead of calling the real
Cloud API, and deliberately simulates occasional rate-limit/timeout
failures so the pipeline's error handling is exercised before any real
credentials exist — a gap the Plan-agent review specifically flagged.
"""
from __future__ import annotations

import random
import uuid

from app.core.providers.base import InboundWhatsAppMessage, ProviderError, WhatsAppProvider


class MockWhatsAppProvider(WhatsAppProvider):
    def __init__(self, failure_rate: float = 0.0):
        self.failure_rate = failure_rate
        self.sent: list[dict] = []

    async def send_message(self, to_phone: str, text: str) -> str:
        if random.random() < self.failure_rate:
            raise ProviderError("Simulated WhatsApp rate-limit/timeout")
        message_id = f"mock-{uuid.uuid4()}"
        self.sent.append({"to": to_phone, "text": text, "id": message_id})
        return message_id

    def parse_webhook(self, payload: dict) -> list[InboundWhatsAppMessage]:
        """Dev webhook shape: {"from": "+91...", "text": "...", "id": "..."}"""
        return [
            InboundWhatsAppMessage(
                from_phone=payload["from"],
                text=payload["text"],
                provider_message_id=payload.get("id", f"mock-in-{uuid.uuid4()}"),
            )
        ]
