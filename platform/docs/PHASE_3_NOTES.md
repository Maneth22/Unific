# Phase 3 — Meeting Room + Plugin Entitlements ("PROMPT 4")

Scope: a new `plugins` schema (`plugin_catalog`, `org_entitlement`)
replacing the Tools Registry's 3 meeting-room-specific slots with a
boolean entitlement gate, and a new `meetings` schema bound to
`orgs.Org`/`orgs.Member`/`orgs.OrgUser` instead of the old
`profiles.Identity` tree — mirroring Prompt 3's "new package, old
untouched" pattern. Resolves ADR-0003's previously-open question about
whether `plugins` replaces the Tools Registry 1:1.

## Decisions made

- **Tools Registry stays unchanged for 4 of its 7 slots.**
  `whatsapp_send`/`reply_generator`/`comms_agent`/`video_provider` and
  their resolution mechanism (`tools_service.py`/`tools_registry.py`/
  `tools_router.py`/`core/models/tools.py`) are untouched — Prompt 3's
  `app/whatsapp/orchestrator.py` and the old `meeting_room/router.py`
  both depend on `tools_service.get_global_tool` for them. Only
  `meeting_stt`/`meeting_tts`/`meeting_translation` are replaced — and
  since the earlier Google-only trim already removed any real per-org
  tool *choice*, the replacement is a pure boolean gate, not a selection
  mechanism.
- **New `meetings` schema, additive, no dual-routing needed.** Unlike
  WhatsApp's single webhook URL, each LiveKit meeting has its own
  dynamically generated `room_name` — no shared physical resource forces
  a dispatch point. `app/meeting_room/*` stays completely untouched by
  this phase.
- **`live_agents.start_for_meeting`/`stop_for_meeting` and
  `VideoProvider` reused as-is** — zero Identity/Org coupling. The new
  `_mark_joined` builds a fixed Google-only `EffectiveToolConfig` inline
  from `settings.live_agents_stt_provider_map_dict`/`_tts_provider_map_dict`
  rather than calling `resolve_effective_tools`.
- **The in-process `_running` agent registry is not replaced wholesale.**
  Its values hold live `MeetingLiveAgent`/`asyncio.Task` objects that
  can't move to Redis without a much larger redesign (a separate LiveKit
  Agents worker deployment) — `docs/adr/0002` already accepted
  single-replica `backend` for exactly this reason. This phase adds a
  Redis-backed **metadata-only** registry (concurrency count +
  visibility), honestly scoped, not a multi-replica fix.
- **`max_concurrent_livekit_sessions` is global, not per-org** — it caps
  how many `MeetingLiveAgent` sessions this one backend replica hosts (a
  CPU/asyncio-task resource), not an inter-org fairness concern. Only
  gates the translation agent; raw video is unaffected.
- **Composite-PK `OrgEntitlement(org_id, plugin_key)`** — mirrors
  `ToolGlobalSelection`'s precedent: inherently unique, `has()` is a
  single indexed PK lookup, no surrogate id.
- **`activated_by` FKs to `core.staff_user`, not `orgs.org_user`** —
  entitlement grants/revokes/suspends are staff/admin actions only, same
  as the rest of the plugin marketplace's admin surface; org users only
  ever read their own org's entitlements.
- **No automatic WhatsApp meeting-invite send** (deferred) — would need
  `app.meetings` importing `app.whatsapp`, a cross-room service
  dependency this codebase reserves for routers, not services. The
  client dashboard surfaces `invite_url` to copy/share instead. Named
  fast-follow for Prompt 5/6.
- **`meeting_kind` dropped** — the old `profiles.Identity` tree's
  ILC/client-org distinction has no equivalent in the flat `orgs` schema,
  so there's nothing left for it to discriminate.
- **`translation_active` persisted on `Meeting`**, not re-derived on
  every read — set once at the `scheduled -> live` transition and never
  rechecked, so a later entitlement revoke never retroactively changes
  what a live meeting reports about itself.

## The translation mechanism itself (user-confirmed, this phase doesn't rebuild it)

Google STT caption extraction, Gemini-based translation, and Google TTS
live-audio translation are exactly what the reused, unchanged
`live_agents` pipeline already does (`captions.py` — Google Chirp 3 STT
per speaker; `translator.py`/`translation_backends.py` — Gemini;
`dubbed_audio.py` — Google Cloud TTS per target language). This phase
adds the entitlement gate around that pipeline, nothing more.

**The "agent phase" indicator** (so participants know a translator is
actively working) is scoped, per the user's explicit choice between a
full in-call announcement system and a plain API flag, to
`meeting.translation_active` surfaced on `JoinResponse` and the admin
`GET /meetings/active-sessions` endpoint. The visible in-UI banner is
Prompt 6 (frontend) work built from that flag — no new in-call
system-announcement mechanism was added to `chat_relay.py`/`captions.py`
this phase.

## What already existed vs. what's new

Already existed and reused as-is: `live_agents.start_for_meeting`/
`stop_for_meeting`, `VideoProvider` (ABC + mock + LiveKit), the Tools
Registry's 4 untouched slots, `orgs.Org`/`Member`/`OrgUser` (Prompt 2).

Net-new: `app/plugins/` package (`models.py`, `services.py`,
`schemas.py`, `router.py`), `app/meetings/` package (`models.py`,
`services.py`, `session_store.py`, `schemas.py`, `router.py`), two
chained migrations (`e6f7a8b9c0d1_plugins_schema.py`,
`f7a8b9c0d1e2_meetings_schema.py`), `RoomName.meetings`/`RoomName.plugins`,
`max_concurrent_livekit_sessions`/`meeting_concurrency_slot_ttl_seconds`
config, 14 new tests across 4 files.

## A recurring forced touch, anticipated this time: SQLAlchemy class-registry collision

Same issue as Prompt 3's `Conversation`/`Message` collision, caught
proactively before hitting the runtime error: `app/meetings/models.py`
was written directly as `OrgMeeting`/`OrgMeetingParticipant`/
`OrgMeetingInvite` (never drafted as bare `Meeting`/`MeetingParticipant`/
`MeetingInvite`), verified via a dual-import sanity check
(`import app.meeting_room.models; import app.meetings.models`) before
proceeding. `__tablename__` stayed plain (`meeting`/`meeting_participant`/
`meeting_invite`) — `schema="meetings"` disambiguates at the DB level.

A second instance of the same underlying issue, at the Postgres level
this time: `meeting_status`/`meeting_invite_kind` enum *type* names
already exist globally (from `meeting_room`'s tables) — Postgres enum
types are database-global, not schema-scoped. The new migration prefixes
its own as `meetings_meeting_status`/`meetings_meeting_invite_kind`.

## Explicit confirmation: old code is unchanged

Verified via `git status`: no file under `app/meeting_room/*` or any of
the Tools Registry's 4-slot files
(`app/core/services/tools_service.py`, `tools_registry.py`,
`app/core/tools_router.py`, `app/core/models/tools.py`) shows a change
introduced by this phase — the diffs those files carry all predate this
session (Phase 0's Google-only trim, Prompt 3's webhook dual-routing
touch). This phase touched only `app/plugins/*`, `app/meetings/*`,
`app/core/models/common.py` (RoomName additions), `app/database.py`
(SCHEMAS tuple), `alembic/env.py` (model imports for autogenerate),
`app/config.py` (two new settings), `app/main.py` (five new router
mounts), two new migrations, and `tests/conftest.py` (added
`meetings_session_store.close_redis()` to the existing teardown
fixture).

## The Redis concurrency registry — what it solves, what it doesn't

Solves: `MAX_CONCURRENT_LIVEKIT_SESSIONS` enforcement for this one
backend replica (a real CPU/asyncio-task cap), and cross-restart
admin-visibility into which meetings are currently live-translating,
without depending on the in-process `_running` dict's ephemeral state.

Doesn't solve: multi-replica agent hosting — `_running`'s live
`MeetingLiveAgent`/`asyncio.Task` objects still can't move to Redis or a
second replica; ADR-0002's single-replica acceptance stands unchanged.

Documented gap: `try_acquire_meeting_slot` reserves a fixed TTL ceiling
(`meeting_concurrency_slot_ttl_seconds`, default 6h), not a
heartbeat-renewed lease. A meeting genuinely running longer than the
ceiling self-heals out of the registry (undercounting occupancy) even
though `_running` still holds it live. Not solved this phase — flagged
as a fast-follow, not silently accepted. `test_meetings_concurrency.py`
proves the self-heal behavior directly (with a short TTL) so the gap is
demonstrated, not just described.

## The core contract, proven by `test_meetings_entitlement_gating.py`

A meeting without the `live_translation` entitlement gets base video
only (`live_agents.start_for_meeting` never called). A meeting with it
gets the translation path (called once, with the fixed Google/Gemini
config). Revoking mid-meeting doesn't kill the current session — a
second participant joining the same already-live meeting never
re-triggers the entitlement check or a second `start_for_meeting` call
(single-check-at-transition, spy call counts stay at 1) — but does block
the *next* meeting scheduled for that org (gets `translation_active =
False`). `test_meetings_concurrency.py` proves the companion contract:
when the global concurrency cap is exhausted, an otherwise-entitled
meeting still degrades to video-only rather than blocking or failing the
join.

## Open questions for Prompt 5/6

- WhatsApp meeting-invite auto-send fast-follow (needs a router-level
  cross-room call, or a small shared notification service).
- Concurrency-slot heartbeat renewal (replace the fixed TTL ceiling with
  periodic renewal tied to the actual `_running` task's lifetime).
- Per-org fairness for live-translation concurrency — currently global
  only; revisit if one org's meetings start starving others in practice.
- `ai_reply_agent_pro` (seeded, `whatsapp_agent_tier` category) is
  unused by any code path yet — its own future phase.
- Old-pipeline admin-transparency unification (carried over from
  Phase 2, still Prompt 5's job).

## Roadmap

Prompt 5 — Staff observability & WhatsApp test console. Prompt 6 —
Frontend: three dashboards (this is where `translation_active` gets its
visible in-call indicator). Prompt 7 — Hardening pass.

## Verification

- `pytest tests/ -v` — 141 passed (123 prior + 18 new: 4 plugin
  entitlement unit tests, 7 meetings-video tests mirroring the old
  meeting_room suite, 3 entitlement-gating tests proving the core
  contract, 4 concurrency tests).
- `alembic upgrade head` clean on both new migrations; downgrade -2 →
  upgrade head round-trips cleanly against the live dev DB, confirmed by
  re-querying seed data and table structure after.
- `git status` confirms `app/meeting_room/*` and the Tools Registry's
  4-slot files carry no changes introduced by this phase.
