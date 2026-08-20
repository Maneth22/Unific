"""Redis-backed session state for the WhatsApp community agent
(`app.agents.whatsapp_community`) — same-day conversation turns and daily
counters live here, not in Postgres. `app.agents.whatsapp_community.
flush_service` moves them to Postgres once, at end of day (or on-demand via
the admin flush route), and this module's own EXPIREAT-everything policy
means a crashed/skipped flush self-heals by simply expiring rather than
growing unbounded — no session key ever outlives the UTC day it was
written for by more than a small buffer.

Key shape (all under `wa:`, one identity_id per WhatsApp-linked member):
  wa:session:{identity_id}             hash   — conversation_config json, created_at
  wa:session:{identity_id}:messages    list   — json-encoded turn dicts, oldest first, trimmed to _MESSAGES_KEEP
  wa:tokens:{identity_id}:{date}       string — cumulative Gemini tokens spent today (see WHATSAPP_SESSION_TOKEN_CAP)
  wa:auto_replies:{identity_id}:{date} string — auto-reply count today (replaces the old Postgres COUNT(Message) query)
  wa:pending_flush                     set    — identity_ids with turns not yet flushed to Postgres

`{date}` is `window_date()` — UTC calendar day, the same boundary the old
`_under_daily_reply_cap` always used, now shared by the token cap and the
EOD flush cron too (see app.config.Settings.eod_flush_hour_utc/minute_utc).
"""
from __future__ import annotations

import json
from datetime import timedelta, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.core.models.common import utcnow

_redis: aioredis.Redis | None = None

# A live session's chat-history reads only ever need the last few turns —
# 64 is generous headroom well beyond that, so trimming here never affects
# behavior, only memory.
_MESSAGES_KEEP = 64

# Session keys outlive UTC midnight by this much, so a scheduled flush that
# runs a few minutes late (see eod_flush_minute_utc) still finds everything.
_FLUSH_BUFFER_SECONDS = 600

_PENDING_FLUSH_KEY = "wa:pending_flush"


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Closes and drops the lazy singleton client so the next `get_redis()`
    call builds a fresh one. Needed under pytest-asyncio, which gives each
    test function its own event loop — a pooled connection from a
    previous test's loop is unusable under a new one (same Windows-
    specific issue `app.database`'s engine pool has; see conftest.py's
    `_dispose_engine_pool_between_tests`). Not needed by the running app
    itself, which has exactly one event loop for its whole process
    lifetime."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def window_date() -> str:
    return utcnow().strftime("%Y-%m-%d")


def seconds_until_next_utc_midnight() -> int:
    now = utcnow()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((tomorrow - now).total_seconds()), 1)


def _session_key(identity_id: str) -> str:
    return f"wa:session:{identity_id}"


def _messages_key(identity_id: str) -> str:
    return f"wa:session:{identity_id}:messages"


def _tokens_key(identity_id: str) -> str:
    return f"wa:tokens:{identity_id}:{window_date()}"


def _auto_replies_key(identity_id: str) -> str:
    return f"wa:auto_replies:{identity_id}:{window_date()}"


async def _touch_expiry(identity_id: str) -> None:
    """Refreshes every key for this identity's session to expire at the
    same next-UTC-midnight(+buffer) instant — called on every write so a
    session that's still active tonight never expires mid-conversation."""
    r = get_redis()
    # `utcnow()` is a NAIVE datetime (UTC wall-clock value, no tzinfo) —
    # calling .timestamp() directly on it makes Python interpret it in the
    # SYSTEM's local timezone, not UTC, silently shifting the computed
    # epoch by the local UTC offset (e.g. -19800s / -5.5h on a UTC+5:30
    # host). That's wrong by construction, not just imprecise: outside a
    # ~5.5h window before UTC midnight this pushed `expire_at` into the
    # PAST, so Redis deleted every session/token/auto-reply key
    # immediately on write. Attach tzinfo explicitly before calling
    # .timestamp() so it's interpreted as the UTC value it actually is.
    expire_at = int(utcnow().replace(tzinfo=timezone.utc).timestamp()) + seconds_until_next_utc_midnight() + _FLUSH_BUFFER_SECONDS
    async with r.pipeline() as pipe:
        pipe.expireat(_session_key(identity_id), expire_at)
        pipe.expireat(_messages_key(identity_id), expire_at)
        pipe.expireat(_tokens_key(identity_id), expire_at)
        pipe.expireat(_auto_replies_key(identity_id), expire_at)
        await pipe.execute()


async def ensure_session(identity_id: str, *, conversation_config: dict) -> None:
    """Creates/refreshes the session hash (idempotent — HSET on an
    existing hash just overwrites the same fields) and marks the identity
    pending flush. Called on every inbound message, not just the first of
    the day, so config changes (e.g. a mid-day `initiate_comms_room` call)
    are picked up immediately."""
    r = get_redis()
    await r.hset(
        _session_key(identity_id),
        mapping={"conversation_config": json.dumps(conversation_config), "created_at": utcnow().isoformat()},
    )
    await r.sadd(_PENDING_FLUSH_KEY, identity_id)
    await _touch_expiry(identity_id)


async def append_turn(identity_id: str, turn: dict) -> None:
    r = get_redis()
    await r.rpush(_messages_key(identity_id), json.dumps(turn))
    await r.ltrim(_messages_key(identity_id), -_MESSAGES_KEEP, -1)
    await r.sadd(_PENDING_FLUSH_KEY, identity_id)
    await _touch_expiry(identity_id)


async def append_turn_if_session_active(identity_id: str, turn: dict) -> None:
    """Best-effort mirror for a manual reply (see
    `meeting_room.services.send_manual_reply`) — only writes if this
    identity already has a live session today; never creates one on its
    own, since a manual reply outside any active auto-reply session
    shouldn't spin up session/token-cap bookkeeping nothing else will read."""
    r = get_redis()
    if not await r.exists(_session_key(identity_id)):
        return
    await append_turn(identity_id, turn)


async def get_recent_turns(identity_id: str, limit: int | None = 16) -> list[dict]:
    """`limit=None` returns every turn still held for today — used by
    `flush_service` when writing everything to Postgres; a bounded limit
    is used for building chat-history context during live replies."""
    r = get_redis()
    start = -limit if limit else 0
    raw = await r.lrange(_messages_key(identity_id), start, -1)
    return [json.loads(item) for item in raw]


async def get_token_usage(identity_id: str) -> int:
    r = get_redis()
    value = await r.get(_tokens_key(identity_id))
    return int(value) if value else 0


async def incr_token_usage(identity_id: str, amount: int) -> int:
    if amount <= 0:
        return await get_token_usage(identity_id)
    r = get_redis()
    total = await r.incrby(_tokens_key(identity_id), amount)
    await _touch_expiry(identity_id)
    return int(total)


async def get_auto_reply_count(identity_id: str) -> int:
    r = get_redis()
    value = await r.get(_auto_replies_key(identity_id))
    return int(value) if value else 0


async def incr_auto_reply_count(identity_id: str) -> int:
    r = get_redis()
    total = await r.incr(_auto_replies_key(identity_id))
    await _touch_expiry(identity_id)
    return int(total)


async def pending_identity_ids() -> list[str]:
    r = get_redis()
    return list(await r.smembers(_PENDING_FLUSH_KEY))


async def clear_session(identity_id: str) -> None:
    """Called only after `flush_service` has successfully committed this
    identity's turns to Postgres — deletes the session hash and message
    list, and drops the identity from the pending set, so a retried flush
    never double-inserts. The token/auto-reply *counters* are deliberately
    left alone: they're per-UTC-day caps that must keep counting against
    the same day even after a mid-day admin flush, and they expire on
    their own at the next UTC midnight regardless."""
    r = get_redis()
    async with r.pipeline() as pipe:
        pipe.delete(_session_key(identity_id))
        pipe.delete(_messages_key(identity_id))
        pipe.srem(_PENDING_FLUSH_KEY, identity_id)
        await pipe.execute()
