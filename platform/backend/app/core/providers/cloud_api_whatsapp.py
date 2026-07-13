"""WhatsApp Cloud API provider — present as a typed stub so wiring in
real credentials later is a config change, not a rewrite. A "group" on
this provider is a broadcast list + 1:1 conversations, per the Flags &
Issues doc: native WhatsApp groups are not delivered to the Cloud API.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.core.providers.base import InboundWhatsAppMessage, ProviderError, WhatsAppProvider

GRAPH_API_BASE = "https://graph.facebook.com/v20.0"


class CloudAPIWhatsAppProvider(WhatsAppProvider):
    def __init__(self):
        self.token = settings.whatsapp_cloud_api_token
        self.phone_number_id = settings.whatsapp_cloud_api_phone_number_id
        if not self.token or not self.phone_number_id:
            raise ProviderError(
                "WhatsApp Cloud API is not configured — set WHATSAPP_CLOUD_API_TOKEN and "
                "WHATSAPP_CLOUD_API_PHONE_NUMBER_ID, or use WHATSAPP_PROVIDER=mock for development."
            )

    async def send_message(self, to_phone: str, text: str) -> str:
        url = f"{GRAPH_API_BASE}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}"}
        body = {"messaging_product": "whatsapp", "to": to_phone, "type": "text", "text": {"body": text}}
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"WhatsApp Cloud API send failed: {exc}") from exc
        data = resp.json()
        return data.get("messages", [{}])[0].get("id", "")

    def parse_webhook(self, payload: dict) -> list[InboundWhatsAppMessage]:
        messages = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") == "text":
                        messages.append(
                            InboundWhatsAppMessage(
                                from_phone=msg["from"],
                                text=msg["text"]["body"],
                                provider_message_id=msg["id"],
                            )
                        )
        return messages
