"""WhatsApp Diagnostics — a staff-only tool for validating the WhatsApp
integration itself, distinct from the Meeting Room's per-identity comms
pipeline in three ways: it targets an arbitrary/unlinked phone number
(never required to resolve to a known identity), it is never gated by
`gate_service.check_and_charge` (there is no identity's balance to
charge), and its cost is UNIFIC's own operational testing cost, billed
to the Accounts room's own agent sub-account via `spend_service` — the
same pattern `meeting_room/services.py` uses for its own operational
costs, just against a different room account.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.models.audit import ActorType
from app.core.models.common import RoomName
from app.core.models.webhook_log import WebhookDirection
from app.core.providers.base import ProviderError, WhatsAppProvider
from app.core.services import audit_service, spend_service, webhook_log_service

WHATSAPP_PROVIDER_LOG_NAME = "whatsapp_cloud_api"
DIAGNOSTICS_AGENT_NAME = "whatsapp_diagnostics"
TEST_SEND_COST = Decimal("0.01")  # nominal — matches meeting_room's OPERATIONAL_COST_PER_REPLY pattern


class WhatsAppDiagnosticsError(Exception):
    pass


async def test_send(
    db: AsyncSession,
    *,
    staff_id: str,
    to_number: str,
    message_type: str,
    text: str | None,
    template_name: str | None,
    template_params: dict | None,
    whatsapp_provider: WhatsAppProvider,
) -> dict:
    """Sends directly via the configured `WhatsAppProvider` to `to_number`
    — the one caller in this codebase allowed to send to a number with no
    linked identity, since this exists to test the integration itself.
    Always writes an audit row and a webhook_log row (outbound) and always
    records the nominal operational spend, whether the send succeeded or
    not — mirrors `meeting_room.services`' "the attempt has a cost, not
    just the success" pattern."""
    if message_type == "text":
        if not text:
            raise WhatsAppDiagnosticsError("text is required when message_type='text'")
    elif message_type == "template":
        if not template_name:
            raise WhatsAppDiagnosticsError("template_name is required when message_type='template'")
    else:
        raise WhatsAppDiagnosticsError("message_type must be 'text' or 'template'")

    provider_message_id: str | None = None
    error_detail: str | None = None
    try:
        if message_type == "text":
            provider_message_id = await whatsapp_provider.send_message(to_number, text)  # type: ignore[arg-type]
        else:
            provider_message_id = await whatsapp_provider.send_template(
                to_number, template_name, template_params or {}  # type: ignore[arg-type]
            )
        success = True
    except ProviderError as exc:
        success = False
        error_detail = str(exc)

    await webhook_log_service.record(
        db,
        room=RoomName.accounts,
        provider=WHATSAPP_PROVIDER_LOG_NAME,
        direction=WebhookDirection.outbound,
        raw_payload={
            "to_number": to_number,
            "message_type": message_type,
            "text": text,
            "template_name": template_name,
            "template_params": template_params,
            "provider_message_id": provider_message_id,
            "error": error_detail,
        },
        status="sent" if success else f"error:{error_detail}",
    )

    await audit_service.record(
        db,
        actor_type=ActorType.staff,
        actor_id=staff_id,
        action="accounts.whatsapp.test_send",
        room=RoomName.accounts,
        entity_type="whatsapp_test_send",
        entity_id=provider_message_id,
        after={"to_number": to_number, "message_type": message_type, "success": success},
    )

    await spend_service.record_spend(
        db,
        room=RoomName.accounts,
        agent_name=DIAGNOSTICS_AGENT_NAME,
        amount=TEST_SEND_COST,
        description=f"WhatsApp test send ({message_type}) to {to_number}",
    )
    await db.flush()

    return {"success": success, "provider_message_id": provider_message_id, "error": error_detail}


def _expected_webhook_url() -> str:
    return f"{settings.backend_base_url.rstrip('/')}/api/meeting-room/webhook"


async def get_webhook_status(whatsapp_provider: WhatsAppProvider) -> dict:
    """Read-only — no audit/spend, mirrors the Financial Dashboard's other
    read-only summary endpoints. A failed lookup (e.g. app credentials not
    configured) is surfaced as `configured=False` with an `error` message,
    never a crash."""
    expected = _expected_webhook_url()
    try:
        config = await whatsapp_provider.get_webhook_configuration()
    except ProviderError as exc:
        return {
            "configured": False,
            "callback_url": None,
            "fields": [],
            "active": False,
            "expected_callback_url": expected,
            "matches": False,
            "error": str(exc),
        }
    matches = bool(config.get("configured")) and config.get("callback_url") == expected and bool(config.get("active"))
    return {
        "configured": bool(config.get("configured")),
        "callback_url": config.get("callback_url"),
        "fields": config.get("fields") or [],
        "active": bool(config.get("active")),
        "expected_callback_url": expected,
        "matches": matches,
        "error": None,
    }
