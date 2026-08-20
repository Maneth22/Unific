# Phase 2 — WhatsApp Service ("PROMPT 3")

Scope: member self-registration via `orgs.GroupInvite` redemption, a new
`whatsapp` schema (`Conversation`/`Message`/`PhoneLink`, bound to
`orgs.Member`), an arq-based inbound pipeline with per-org concurrency
and LLM-spend caps, a client dashboard API, and a staff-facing admin
transparency view — WhatsApp users, their group, and their client org, in
one place, per the user's explicit request this phase.

## Decisions made

- **Dual-routed webhook** (user-locked): one physical endpoint
  (`POST /api/meeting-room/webhook`, same URL Meta already calls). A
  phone number found in `whatsapp.phone_link` dispatches to the new
  arq-based pipeline; everything else falls through to the old,
  untouched, in-process pipeline. No data migration.
- **Idempotency**: a Redis SETNX-with-TTL
  (`whatsapp.session_store.claim_provider_message_id`) at the shared
  webhook entry point, before either pipeline is dispatched to — fixes a
  real, previously-existing gap (no dedup existed anywhere) for **both**
  pipelines from one change. Backed by a second, independent DB-level
  unique index on `whatsapp.message.provider_message_id` (the old
  table's equivalent column was never indexed).
- **Per-org LLM spend cap**: new concept, new `whatsapp:spend:` Redis
  key, atomic Lua reserve-then-adjust (reserve a conservative ceiling
  before the Gemini call sequence starts, true up once the real cost is
  known).
- **Per-org concurrency caps**: a Redis sorted-set semaphore
  (`whatsapp:sem:`), self-healing via TTL pruning — arq itself ships no
  per-org primitive (confirmed by reading `arq==0.28.0`'s source:
  `max_jobs` is a single whole-process cap across every job/org
  combined, not per-org).
- **Per-member token cap**: reused verbatim from the OLD
  `app.agents.whatsapp_community.session_store`'s `wa:tokens:{id}:{date}`
  counter, keyed by `member.id` instead of `identity.id` — not a new,
  disconnected Redis store. This was forced by Finding D below, not a
  stylistic choice.
- **Conversation/message storage**: direct per-message Postgres writes
  from the arq job — no Redis turn-buffering. The old pipeline's
  Redis-buffering exists specifically to keep the webhook's synchronous
  request fast; that constraint doesn't apply to an arq job, which is
  already off the request path.
- **EOD flush**: the old pipeline's APScheduler flush job is untouched.
  The new pipeline needs no flush job at all — there's nothing to flush.
- **Admin transparency scope**: built now for the NEW pipeline only (see
  below) — the OLD pipeline's linked members are a named Prompt 5
  fast-follow, not silently omitted.

## Finding D — the second sanctioned old-pipeline-adjacent touch

Reusing the existing Gemini provider implementations
(`gemini_reply_generator.py`, `gemini_comms_agent.py`) for the new
pipeline exactly as-is would have crashed it. Both unconditionally call
`llm_usage_service.record_usage(..., identity_id=identity_id, ...)`, and
`core.llm_usage_record.identity_id` is a real FK to
`profiles.identity.id` — passing a `member.id` there raises an uncaught
`IntegrityError`, not a `ProviderError`, so the orchestrator's
degrade-and-log pattern doesn't catch it. Passing `identity_id=None`
instead would have silently disabled the per-member token-cap counter
(`session_store.incr_token_usage` is gated on `identity_id is not None`).

**Resolution**: additively widened, mirroring how Prompt 2 added
`ActorType.org_user` alongside the existing enum values — every existing
call site keeps working unchanged (new params default to `None`):

- `core.llm_usage_record` gained a nullable `member_id` FK (+ a CHECK
  that at most one of `identity_id`/`member_id` is ever set).
- `llm_usage_service.record_usage(..., member_id=None)`.
- `ReplyGenerator.generate_reply` and all six `CommsAgent` ABC methods
  gained an optional `member_id: str | None = None`.
- `gemini_reply_generator.py`/`gemini_comms_agent.py` thread it through
  and prefer it over `identity_id` for the token-cap increment when both
  could theoretically apply (in practice, never both — see the CHECK).
- `mock_comms_agent.py`/`stub_reply_generator.py` got the same
  signature-only addition to keep matching the ABC.
- `tests/test_old_pipeline_llm_usage_unchanged.py` proves it: a real
  old-pipeline-shaped Gemini call (mocked `generate`, `identity_id` set,
  `member_id` never passed) still writes `identity_id` set / `member_id`
  NULL.

## A third forced touch, not anticipated in the plan: SQLAlchemy class-registry collision

This codebase shares **one** declarative `Base`/class registry across
every room. Naming the new models `Conversation`/`Message` (matching the
directive's literal wording and `meeting_room.models`' own names)
produced `sqlalchemy.exc.InvalidRequestError: Multiple classes found for
path "Message"` the moment both modules were imported together —
`Mapped["Message"]`-style forward references and `order_by=` strings
resolve against that single shared registry, so a same-named class
anywhere else in the app is ambiguous even with a fully-qualified string
argument to `relationship()` (tried first; didn't fully resolve the
annotation-driven half of the lookup). **Resolved by renaming the new
classes to `WhatsappConversation`/`WhatsappMessage`** (imported with a
local `as Conversation`/`as Message` alias inside `app/whatsapp/*` for
readability) — `__tablename__` stayed plain (`conversation`/`message`)
since `schema="whatsapp"` already disambiguates at the DB level; only
the Python class names needed to change. This kept `meeting_room/models.py`
completely untouched, which a same-registry-forced fix on that side
would not have.

## What already existed vs. what's new

Already existed and reused as-is: the `WhatsAppProvider`/`CommsAgent`/
`ReplyGenerator` ABCs and every implementation (mock, Cloud API, Gemini,
stub) — the directive's item 2 asked to build these, but they were
already fully built in Prompt-1/2-era work; `orgs.GroupInvite` and
`orgs.services.create_group_invite` (Prompt 2); the arq skeleton
(Phase 0) — this phase adds its first real job.

Net-new: `app/whatsapp/` package (`models.py`, `services.py`,
`orchestrator.py`, `session_store.py`, `schemas.py`, `router.py`),
migration `d5e6f7a8b9c0_whatsapp_schema.py`, `orgs.services.
get_invite_by_token`/`register_member`, six new test files, an arq
producer pool wired into `app.main`'s lifespan.

## Explicit confirmation: old pipeline behavior is unchanged

Verified via `git status`: every file touched in
`app/agents/whatsapp_community/*` this phase is one of the four Finding-D
provider files, each additive-only (new optional kwarg, default `None`,
proven by regression test). `app/profiles/*`, `app/accounts/*`,
`app/meeting_room/services.py`, `app/meeting_room/models.py`, and
`app/meeting_room/live_agents/*` were not touched at all in this phase —
only `app/meeting_room/router.py`'s `inbound_webhook` function gained the
idempotency claim + dual-routing dispatch, with the pre-existing old-pipeline
call left byte-for-byte identical. The full 123-test suite (113 prior +
10 new) passes; a dedicated test
(`test_whatsapp_webhook_idempotency.py::test_old_pipeline_duplicate_webhook_delivery_processed_once`)
drives a real old-pipeline-linked number through the real webhook route
and confirms unchanged "processed" behavior on first delivery.

## Admin transparency — what's covered now, what's a fast-follow

`GET /api/whatsapp/member-directory` (staff, admin-only): every member
in the new pipeline, their group, and their org, via one flat join —
trivial because Prompt 2's `orgs` schema has no tree to walk.

**Not covered yet, on purpose, flagged as a Prompt 5 item**: the OLD
pipeline's `WhatsAppLink`-linked identities. Unifying them into the same
view needs `scope_service`'s path-walk per `Identity` row — a materially
different query shape and a different id space (`Identity.id` vs
`Member.id`) than the new pipeline's flat join. Recommendation: add a
`pipeline: "new"|"legacy"` discriminator field to the same response
shape, built in the Staff Observability phase (Prompt 5), which the
roadmap already earmarks for cross-pipeline visibility work
(`agent_run_log` wiring). This means every new org signup gets full
transparency starting now; existing already-linked numbers join the same
view on a named, scheduled next step — not silently left out forever.

## Open questions for Prompt 4/5

- Old-pipeline admin-transparency unification (above) — Prompt 5.
- No per-org Tools Registry override exists in the `orgs` schema yet
  (Prompt 2 has no `Permission` equivalent) — every org shares the same
  global `comms_agent`/`reply_generator`/`whatsapp_send` selection.
  Candidate for Prompt 4's plugin entitlements.
- `whatsapp.services.room_config` is a simplified fallback (fixed
  role/tone/complexity defaults) since there's no `Permission.effective_*`
  cascade to inherit from — whether `Org`/`Group` need their own
  reply-config columns to restore per-org customization is open.
- `context_snippets` is always `[]` for the new pipeline's reply
  generation — the old pipeline's `_approved_context` reads the Archive
  Locker, a `meeting_room`-scoped concept with no `orgs`-schema
  equivalent. A per-org knowledge base/RAG lookup is a future phase's
  job, not solved here.
- `whatsapp_org_spend_reservation_usd` ($0.02, a conservative per-message
  ceiling covering up to 4 Gemini calls) needs tuning against real usage
  once live traffic exists.
- No pre-instructed-member ("client_added") reconciliation exists in the
  new `register_member` — every invite redemption creates a fresh
  `Member` row, unlike the legacy `IlcMemberRoster`-gated flow. Whether
  that workflow is needed for the new schema is open.

## Roadmap

Prompt 4 — Meeting Room + plugin entitlements. Prompt 5 — Staff
observability & WhatsApp test console (this is where `agent_run_log`
call sites get wired, and where the admin-transparency unification
above is budgeted). Prompt 6 — Frontend: three dashboards. Prompt 7 —
Hardening pass.

## Verification

- `pytest tests/ -v` — 123 passed (113 existing + 10 new: 3 registration,
  2 webhook idempotency — one per pipeline, 2 spend cap, 2 concurrency,
  1 Finding-D regression).
- `alembic upgrade head` clean; `alembic downgrade -1` → `upgrade head`
  round-trips cleanly against the live dev DB.
- `git status` confirms the touch list matches exactly what's described
  above — no unexpected files.
