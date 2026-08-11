"""WhatsApp Cloud API provider. A "group" on this provider is a broadcast
list + 1:1 conversations, per the Flags & Issues doc: native WhatsApp
groups are not delivered to the Cloud API.

The GET verification handshake (`verify_handshake` below) is a pure,
router-independent function deliberately kept separate from the FastAPI
route itself — routes live in `app.meeting_room.router` per this
codebase's convention (see `docs/ARCHITECTURE.md`'s room contract), but
the token-comparison logic is Cloud-API-specific and belongs with the
rest of this provider.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.core.providers.base import InboundWhatsAppMessage, ProviderError, WhatsAppProvider

logger = logging.getLogger(__name__)


def verify_handshake(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """Meta's GET subscription-verification handshake: returns `challenge`
    unchanged if `mode == "subscribe"` and `token` matches the configured
    verify token, else None (the route returns 403 for None)."""
    if mode != "subscribe" or challenge is None:
        return None
    if not settings.whatsapp_cloud_api_verify_token or token != settings.whatsapp_cloud_api_verify_token:
        return None
    return challenge


class CloudAPIWhatsAppProvider(WhatsAppProvider):
    def __init__(self):
        self.token = settings.whatsapp_cloud_api_token
        self.phone_number_id = settings.whatsapp_cloud_api_phone_number_id
        self.graph_api_base = f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        if not self.token or not self.phone_number_id:
            raise ProviderError(
                "WhatsApp Cloud API is not configured — set WHATSAPP_CLOUD_API_TOKEN and "
                "WHATSAPP_CLOUD_API_PHONE_NUMBER_ID, or use WHATSAPP_PROVIDER=mock for development."
            )

    async def send_message(self, to_phone: str, text: str) -> str:
        url = f"{self.graph_api_base}/{self.phone_number_id}/messages"
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

    async def send_template(self, to_phone: str, template_name: str, params: dict) -> str:
        """`params` is the template's body-component parameter list, e.g.
        `{"body_params": ["Alex", "Tuesday"]}` — positional, matching the
        template's own `{{1}}`/`{{2}}` placeholders in order. Language
        defaults to `en_US`; pass `params={"language": "en", ...}` to
        override."""
        url = f"{self.graph_api_base}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}"}
        body_params = params.get("body_params") or []
        language = params.get("language", "en_US")
        body = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": (
                    [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in body_params]}]
                    if body_params
                    else []
                ),
            },
        }
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                raise ProviderError(f"WhatsApp Cloud API template send failed: {detail}") from exc
        data = resp.json()
        return data.get("messages", [{}])[0].get("id", "")

    def parse_webhook(self, payload: dict) -> list[InboundWhatsAppMessage]:
        """Every field here is untrusted input straight off the wire —
        `.get()` throughout, and a malformed entry/change/message is
        skipped (logged, not raised) rather than taking down the whole
        webhook request over one bad item in the batch."""
        messages: list[InboundWhatsAppMessage] = []
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value") or {}
                for msg in value.get("messages") or []:
                    if not isinstance(msg, dict) or msg.get("type") != "text":
                        continue
                    from_phone = msg.get("from")
                    body = (msg.get("text") or {}).get("body")
                    message_id = msg.get("id")
                    if not from_phone or body is None or not message_id:
                        logger.warning("Skipping malformed inbound WhatsApp message: %r", msg)
                        continue
                    messages.append(
                        InboundWhatsAppMessage(from_phone=from_phone, text=body, provider_message_id=message_id)
                    )
        return messages

    async def get_webhook_configuration(self) -> dict:
        """Reads Meta's `/{app-id}/subscriptions` edge — the app-level
        webhook config (callback URL, subscribed fields, active flag),
        distinct from anything the phone-number-scoped token above can
        see. Requires an app access token (`app_id|app_secret`), which is
        a separate credential pair from the system-user token used for
        sends — see `whatsapp_cloud_api_app_id`/`_app_secret`."""
        app_id = settings.whatsapp_cloud_api_app_id
        app_secret = settings.whatsapp_cloud_api_app_secret
        if not app_id or not app_secret:
            raise ProviderError(
                "Webhook status is unavailable — set WHATSAPP_CLOUD_API_APP_ID and "
                "WHATSAPP_CLOUD_API_APP_SECRET (Meta App Dashboard > Settings > Basic)."
            )
        url = f"{self.graph_api_base}/{app_id}/subscriptions"
        params = {"access_token": f"{app_id}|{app_secret}"}
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                raise ProviderError(f"WhatsApp Cloud API subscriptions lookup failed: {detail}") from exc
        data = resp.json()
        for sub in data.get("data") or []:
            if sub.get("object") == "whatsapp_business_account":
                return {
                    "configured": True,
                    "callback_url": sub.get("callback_url"),
                    "fields": [f.get("name") for f in (sub.get("fields") or []) if isinstance(f, dict)],
                    "active": bool(sub.get("active", False)),
                }
        return {"configured": False, "callback_url": None, "fields": [], "active": False}
