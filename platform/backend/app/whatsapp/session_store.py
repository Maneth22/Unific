"""New-pipeline Redis state: per-org LLM spend cap, per-org concurrency
semaphores, and webhook-entry-point idempotency — deliberately NOT a
parallel copy of `app.agents.whatsapp_community.session_store`'s
conversation-turn/token-cap bookkeeping.

Per-member conversation turns are not buffered here at all: the new
pipeline writes `whatsapp.Message` rows directly to Postgres per message
(see `services.py`), since it already runs inside an arq job — off the
webhook's synchronous request path, unlike the old pipeline, whose
Redis-buffering exists specifically to keep that request fast. Per-member
token-cap bookkeeping (the existing `whatsapp_session_token_cap`/day
limit) is deliberately NOT duplicated under a new key prefix either — it
stays owned by the OLD module's `wa:tokens:{id}:{date}` counter, which
`GeminiReplyGenerator`/`GeminiCommsAgent` already write to for whichever
principal (`identity_id` or `member_id`) triggered the call (see
docs/PHASE_2_NOTES.md's "Finding D"). Duplicating it under a `whatsapp:`
prefix here would silently break the cap: writes would land under
`wa:tokens:`, a new-prefix reader would always see zero.

Everything under this module's own `whatsapp:` prefix is genuinely new —
no old-pipeline concept had an equivalent.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncIterator, Literal

import redis.asyncio as aioredis

from app.agents.whatsapp_community.session_store import window_date
from app.config import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Same lazy-singleton teardown as the old module's `close_redis` —
    needed under pytest-asyncio's per-test event loop; see that module's
    docstring for the full reasoning."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def _spend_key(org_id: str) -> str:
    return f"whatsapp:spend:{org_id}:{window_date()}"


def _semaphore_key(kind: str, org_id: str) -> str:
    return f"whatsapp:sem:{kind}:{org_id}"


def _idempotency_key(provider_message_id: str) -> str:
    return f"whatsapp:seen:{provider_message_id}"


# --- Per-org LLM spend cap (atomic reserve-then-adjust) --------------------

_SPEND_RESERVE_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local reservation = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
if current + reservation > cap then
  return 0
end
redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


async def reserve_org_spend(org_id: str, *, reservation_usd: Decimal, cap_usd: Decimal, ttl_seconds: int) -> bool:
    """Atomically reserves `reservation_usd` against `org_id`'s today
    counter if doing so would not exceed `cap_usd`; returns False
    (reject) otherwise. Called BEFORE the Gemini call sequence starts —
    actual cost is only known after clarify/tone/reply/translate all
    complete, so this reserves a conservative per-message ceiling up
    front (see `adjust_org_spend` for the true-up)."""
    r = get_redis()
    result = await r.eval(
        _SPEND_RESERVE_LUA, 1, _spend_key(org_id), str(reservation_usd), str(cap_usd), str(ttl_seconds),
    )
    return bool(int(result))


async def adjust_org_spend(org_id: str, *, delta_usd: Decimal) -> None:
    """INCRBYFLOAT by (actual_cost - reservation) once the real cost is
    known — may be negative (a refund). A single INCRBYFLOAT is already
    atomic; no Lua needed here."""
    if delta_usd == 0:
        return
    r = get_redis()
    await r.incrbyfloat(_spend_key(org_id), float(delta_usd))


async def get_org_spend_today(org_id: str) -> Decimal:
    r = get_redis()
    value = await r.get(_spend_key(org_id))
    return Decimal(value) if value else Decimal("0")


# --- Per-org concurrency semaphores (Redis sorted-set) ----------------------
# Mirrors arq's OWN internal queue-management approach (a sorted set of
# active holders), self-healing via TTL pruning so a crashed holder that
# never released doesn't permanently jam the semaphore.

_SEM_ACQUIRE_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


class OrgConcurrencyTimeout(Exception):
    """Raised when a concurrency slot doesn't free up within
    `max_wait_seconds` — the caller should treat this like a
    `ProviderError`-shaped degrade (log, don't crash), not fatal."""


async def try_acquire_org_slot(
    kind: Literal["send", "llm"], org_id: str, holder_id: str, *, limit: int, hold_ttl_seconds: int = 30
) -> bool:
    """`kind='send'` -> MAX_CONCURRENT_WHATSAPP_SENDS_PER_ORG, `kind='llm'`
    -> MAX_CONCURRENT_LLM_CALLS_PER_ORG. Prunes stale (crashed) holders
    older than `hold_ttl_seconds` before checking occupancy, so a holder
    that dies without calling `release_org_slot` self-heals rather than
    permanently occupying a slot."""
    r = get_redis()
    now = time.time()
    stale_before = now - hold_ttl_seconds
    result = await r.eval(
        _SEM_ACQUIRE_LUA, 1, _semaphore_key(kind, org_id),
        str(stale_before), str(limit), str(now), holder_id, str(hold_ttl_seconds),
    )
    return bool(int(result))


async def release_org_slot(kind: str, org_id: str, holder_id: str) -> None:
    """Always call in a `finally` block — see `org_concurrency_slot`."""
    r = get_redis()
    await r.zrem(_semaphore_key(kind, org_id), holder_id)


@asynccontextmanager
async def org_concurrency_slot(
    kind: Literal["send", "llm"], org_id: str, *, limit: int, poll_interval: float = 0.25, max_wait_seconds: float = 30.0
) -> AsyncIterator[None]:
    """Blocks (short-polls `try_acquire_org_slot`) until a slot frees or
    `max_wait_seconds` elapses, then raises `OrgConcurrencyTimeout` — this
    is what makes "excess queues rather than all running at once"
    concretely testable."""
    holder_id = uuid.uuid4().hex
    deadline = time.monotonic() + max_wait_seconds
    while True:
        acquired = await try_acquire_org_slot(
            kind, org_id, holder_id, limit=limit, hold_ttl_seconds=settings.whatsapp_concurrency_slot_ttl_seconds
        )
        if acquired:
            break
        if time.monotonic() >= deadline:
            raise OrgConcurrencyTimeout(f"Timed out waiting for a {kind!r} concurrency slot for org {org_id}")
        await asyncio.sleep(poll_interval)
    try:
        yield
    finally:
        await release_org_slot(kind, org_id, holder_id)


# --- Webhook-entry-point idempotency (shared by BOTH pipelines) -----------


async def claim_provider_message_id(provider_message_id: str, *, ttl_seconds: int = 86400) -> bool:
    """SETNX-with-TTL — True if this is the first time this
    `provider_message_id` has been seen, False if it's a duplicate
    (already claimed). Called once, in `app.meeting_room.router`'s
    inbound webhook handler, BEFORE branching into old-vs-new pipeline
    dispatch — fixes a real, previously-existing gap (no idempotency
    check existed anywhere) for both pipelines from one change. An empty
    `provider_message_id` (a malformed/mock payload) is never treated as
    a duplicate — there's nothing meaningful to dedupe on."""
    if not provider_message_id:
        return True
    r = get_redis()
    result = await r.set(_idempotency_key(provider_message_id), "1", nx=True, ex=ttl_seconds)
    return bool(result)
