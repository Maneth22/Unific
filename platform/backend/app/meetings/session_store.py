"""A Redis-backed, GLOBAL (not per-org) registry for live-translation
agent concurrency + cross-restart visibility. Deliberately NOT a
replacement for `app.meeting_room.live_agents.orchestrator`'s in-process
`_running` dict — that dict's values hold live `MeetingLiveAgent`/
`asyncio.Task` objects, which cannot be serialized into Redis or shared
across processes without a much larger redesign (a separate LiveKit
Agents worker deployment). This repo's own `docs/adr/0002` already
accepted that the `backend` service stays single-replica for exactly
this reason — this module doesn't fight that, it solves the two things
that ARE solvable without it:

1. `MAX_CONCURRENT_LIVEKIT_SESSIONS` enforcement — how many
   `MeetingLiveAgent` sessions this one backend replica hosts in-process
   at once (a CPU/asyncio-task resource), gating only the translation
   agent, never raw LiveKit video (which is unaffected and always
   available).
2. Cross-restart / admin-view visibility of which meetings are currently
   live-translating, without depending on `_running`'s in-process state.

Global, not per-org: unlike WhatsApp's per-org send/LLM-call semaphores
(a real inter-org fairness concern with many orgs plausibly messaging at
once), a live-translation session is a CPU-heavy, whole-process resource
on a single-replica backend — a per-org cap would let one org's several
simultaneous meetings starve everyone else even with process-wide
headroom, or add pointless friction when only one org is active.

Known, documented gap: `try_acquire_meeting_slot` reserves a slot for a
fixed TTL ceiling, not a heartbeat-renewed lease — a meeting genuinely
running longer than `meeting_concurrency_slot_ttl_seconds` self-heals out
of the registry (undercounting occupancy) even though `_running` still
holds it. Not solved this phase; flagged as a fast-follow.
"""
from __future__ import annotations

import time

import redis.asyncio as aioredis

from app.config import settings

_redis: aioredis.Redis | None = None

_ACTIVE_MEETINGS_KEY = "meetings:active"


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Same lazy-singleton teardown as `app.whatsapp.session_store`'s —
    needed under pytest-asyncio's per-test event loop."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


_ACQUIRE_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
return 1
"""


async def try_acquire_meeting_slot(meeting_id: str, *, limit: int, ttl_seconds: int) -> bool:
    """Prunes entries whose reservation has expired (score <= now),
    checks occupancy against `limit`, admits with score=now+ttl_seconds
    if there's room. Self-healing: a crashed backend that never calls
    `release_meeting_slot` frees its slot once the TTL elapses."""
    r = get_redis()
    now = time.time()
    result = await r.eval(_ACQUIRE_LUA, 1, _ACTIVE_MEETINGS_KEY, str(now), str(limit), str(now + ttl_seconds), meeting_id)
    return bool(int(result))


async def release_meeting_slot(meeting_id: str) -> None:
    """ZREM — safe to call even if this meeting_id was never admitted
    (not entitled, or admission failed); always call in a best-effort
    try/except at end_meeting/delete_meeting, mirroring
    app.whatsapp.session_store's release discipline."""
    r = get_redis()
    await r.zrem(_ACTIVE_MEETINGS_KEY, meeting_id)


async def list_active_meetings() -> list[tuple[str, float]]:
    """Prunes stale entries, then returns (meeting_id, expires_at) pairs —
    backs an admin observability endpoint."""
    r = get_redis()
    now = time.time()
    await r.zremrangebyscore(_ACTIVE_MEETINGS_KEY, "-inf", now)
    rows = await r.zrange(_ACTIVE_MEETINGS_KEY, 0, -1, withscores=True)
    return [(meeting_id, score) for meeting_id, score in rows]


async def count_active_meetings() -> int:
    r = get_redis()
    now = time.time()
    await r.zremrangebyscore(_ACTIVE_MEETINGS_KEY, "-inf", now)
    return await r.zcard(_ACTIVE_MEETINGS_KEY)
