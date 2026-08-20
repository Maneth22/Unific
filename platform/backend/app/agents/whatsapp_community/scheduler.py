"""In-process scheduler for the WhatsApp community agent's end-of-day
flush. `AsyncIOScheduler`, not Celery — this app has zero broker/worker
infrastructure today (no Redis-as-broker, no Celery beat), and the one
existing precedent for background async work in this codebase
(`app.meeting_room.live_agents`) already runs in-process via
`asyncio.create_task` rather than a separate deploy artifact. Wired into
`app.main`'s `lifespan()`, right where the video-provider Tools Registry
warmup (`tools_service.get_global_tool(db, ToolSlot.video_provider)`) runs.

Single-instance only: if this app is ever horizontally scaled to more than
one process, only one instance may run this scheduler (leader election, or
a dedicated worker instance) — otherwise every instance would flush the
same identities concurrently. Out of scope for the current single-instance
deployment (one docker-compose Postgres, one uvicorn process).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.agents.whatsapp_community.flush_service import flush_all_sessions
from app.config import settings

logger = logging.getLogger(__name__)


async def _run_scheduled_flush() -> None:
    result = await flush_all_sessions()
    logger.info("Scheduled WhatsApp session flush complete: %s", result)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_scheduled_flush,
        CronTrigger(hour=settings.eod_flush_hour_utc, minute=settings.eod_flush_minute_utc),
        id="whatsapp_community_eod_flush",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "WhatsApp community agent EOD flush scheduled for %02d:%02d UTC daily",
        settings.eod_flush_hour_utc, settings.eod_flush_minute_utc,
    )
    return scheduler
