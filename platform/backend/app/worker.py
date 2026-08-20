"""arq worker entry point.

Phase 0 stood this up as a zero-business-logic skeleton (one placeholder
`healthcheck` job) to prove the `worker` docker-compose service boots and
connects to Redis. This phase (Prompt 3 — WhatsApp service) adds the
first real job: `process_inbound_whatsapp_message`, the NEW WhatsApp
pipeline's own entry point, enqueued by `app.meeting_room.router`'s
webhook handler for any phone number found in `whatsapp.PhoneLink`.

The existing WhatsApp end-of-day flush cron
(`app.agents.whatsapp_community.scheduler`, APScheduler-based, wired into
`app.main`'s lifespan) is untouched and keeps running inside the `backend`
process — the new pipeline writes directly to Postgres per message (see
`app.whatsapp.services.append_message`), so it has no flush job of its
own to migrate here; see docs/PHASE_2_NOTES.md.

Run locally with: `arq app.worker.WorkerSettings`
"""
from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def healthcheck(ctx: dict) -> str:
    """Placeholder job proving the worker can execute something."""
    return "ok"


async def process_inbound_whatsapp_message(
    ctx: dict, *, from_phone: str, text: str, provider_message_id: str
) -> dict:
    """The new pipeline's own entry point — runs in the arq worker pool,
    off the webhook's synchronous request path. Idempotency is already
    guaranteed by the webhook's `claim_provider_message_id` SETNX before
    this job was ever enqueued (see `app.meeting_room.router`) — no
    `_job_id` uniqueness is set on enqueue; a second SETNX-protected claim
    would be belt-and-suspenders overkill arq's unique-job machinery
    doesn't meaningfully add to. The DB-level unique index on
    `whatsapp.message.provider_message_id` is the independent second
    backstop (see `app.whatsapp.models.Message`) — if a retry ever did
    slip through, that constraint prevents a duplicate insert."""
    from app.core.models.tools import ToolSlot
    from app.core.services import tools_service
    from app.whatsapp import orchestrator as whatsapp_orchestrator

    async with AsyncSessionLocal() as db:
        try:
            whatsapp_provider = await tools_service.get_global_tool(db, ToolSlot.whatsapp_send)
            result = await whatsapp_orchestrator.receive_inbound_message(
                db, from_phone=from_phone, text=text, provider_message_id=provider_message_id,
                whatsapp_provider=whatsapp_provider,
            )
            await db.commit()
            return {"status": "processed", "member_id": result.member_id}
        except whatsapp_orchestrator.Bounced as exc:
            await db.rollback()
            return {"status": "bounced", "reason": exc.reason}
        except Exception:
            await db.rollback()
            logger.exception(
                "process_inbound_whatsapp_message failed for provider_message_id=%s", provider_message_id
            )
            raise  # let arq's own retry/backoff handle transient failures


class WorkerSettings:
    functions = [healthcheck, process_inbound_whatsapp_message]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # A whole-PROCESS cap across every job type and every org combined —
    # NOT per-org (arq ships no per-org primitive). Per-org concurrency
    # lives inside the job itself, via app.whatsapp.session_store's Redis
    # semaphore.
    max_jobs = settings.arq_worker_max_jobs
