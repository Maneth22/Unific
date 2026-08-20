# Phase 0 — In-place bootstrap & decisions

Scope: bootstrap only, zero business-logic changes, per the UNIFIC v2
rebuild directive's "PROMPT 1." Alongside it, a separate direct request
was executed to make the meeting-translation/live-captions provider stack
Google-only.

## Decisions made

- **[ADR-0001](adr/0001-frontend-app-topology.md)** — keep the single Vite
  SPA with three route trees (already proven in `App.jsx`). Known risk not
  fixed here: staff/client share one in-memory token slot in
  `api/client.js` — backlog item for the frontend-dashboards rebuild
  phase.
- **[ADR-0002](adr/0002-job-queue-arq.md)** — arq over Celery. Reuses the
  existing Redis container, zero new infra. Migrating the WhatsApp
  EOD-flush cron off APScheduler onto arq is deferred to the WhatsApp
  service rebuild phase.
- **[ADR-0003](adr/0003-target-schema-plan.md)** — documents the target
  five-schema layout (`core`/`orgs`/`whatsapp`/`meetings`/`plugins`).
  Status: Proposed — no migration has run, the database is still on the
  old five-schema layout (`core`/`accounts`/`profiles`/`meeting_room`/
  `tasking`).

## What already existed vs. what Phase 0 added

| Already existed | Added in Phase 0 |
|---|---|
| FastAPI skeleton, async SQLAlchemy engine/session | `docs/adr/0001-0003.md` |
| Alembic config + migrations (old 5-schema scheme) | `docs/legacy/` relocation + banner |
| Naming-convention metadata, audit pattern, provider ABC+mock pattern, JWT-audience pattern | New root `platform/README.md` stub |
| `postgres`+`redis` docker-compose services | `backend`+`worker` docker-compose services |
| pytest + pytest-asyncio infra, 13 test modules | `backend/Dockerfile`, `.dockerignore` |
| `GET /api/health` endpoint (existed but untested) | `arq` dependency + `app/worker.py` skeleton |
| | `tests/test_health.py` (the smoke test the directive asked for — the endpoint existed but nothing exercised it) |

## Google-only meeting translation/STT/TTS trim

Separate from Phase 0's own scope, but executed in the same pass since it
was a direct, low-risk request touching WIP already in flight (not
directive "old code to cut later"):

- `app/meeting_room/live_agents/providers.py`: `STT_FACTORIES`/
  `TTS_FACTORIES` now only register Google (Chirp 3 STT, Google Cloud
  TTS). Deepgram/Azure/OpenAI STT and Azure/ElevenLabs TTS factories
  removed.
- `app/meeting_room/live_agents/translation_backends.py`: only Gemini
  remains; `openai_translation_backend.py` deleted.
- `app/core/services/tools_registry.py`: `_MEETING_STT_KEYS`/
  `_MEETING_TTS_KEYS`/`_MEETING_TRANSLATION_KEYS` narrowed to Google-only
  (`{"google"}`/`{"google"}`/`{"gemini"}`).
- `alembic/versions/a1b2c3d4e5f6_tool_catalog_and_global_selection.py`
  (still-uncommitted WIP): catalog seed rows for the removed providers
  dropped, so the admin Tools Registry UI doesn't offer options that
  would immediately fail. Re-ran (`alembic downgrade` → `upgrade`) against
  the local dev DB so `core.tool_global_selection`'s per-language defaults
  actually reflect Google-only — the migration reads
  `settings.live_agents_stt_provider_map`/`tts_provider_map` live at
  migration-run time, so it wasn't a code change, just a re-seed.
- `requirements.txt`: `livekit-agents[deepgram,azure,google,openai,elevenlabs,silero]`
  → `livekit-agents[google,silero]`; `openai` package dependency dropped
  entirely (verified no other call site imports it).
- `app/config.py`, `.env`, `.env.example`: dropped `deepgram_api_key`,
  `azure_speech_key`/`_region`, `openai_api_key`, `live_agents_openai_model`,
  `elevenlabs_api_key`. STT provider map defaults to all-`google`.
  **Open risk**: TTS provider map only covers Hindi (`hi-IN-Standard-A`)
  — Sinhala (`si`) dubbed audio is deliberately left unmapped until a
  verified `si-LK` voice is confirmed against Google Cloud TTS's current
  voice catalog; captions-only still works for `si` via the STT map.
- `tests/test_tools_registry.py`: three tests that depended on two
  distinct meeting-room provider values (now only one exists for
  `meeting_stt`/`meeting_tts`/`meeting_translation`) were adjusted —
  either to assert the override *mechanism* directly (own_* column) where
  the resolved value can no longer differ, or switched to exercise
  `comms_agent` (which still has two real options: gemini/mock) for tests
  whose actual point was generic cascade/snapshot behavior, not something
  meeting-translation-specific.
- **Frontend**: no changes needed — verified no hardcoded provider-key
  lists exist in `platform/frontend/src`; the Tools Registry panel already
  sources its option list from the backend.
- **Security note**: `.env.example` had a real-looking Deepgram API key
  committed in plaintext (`DEEPGRAM_API_KEY=436fcf6ee861f558bd224...`),
  present across multiple prior commits. Removing the line here doesn't
  scrub it from git history — **rotate that key if it's live**, and
  consider whether history needs cleaning.

Verified: full backend test suite (107 tests) passes; `docker compose
build backend worker && up -d` brings up all four services cleanly;
`GET /api/health` returns `200`; the `worker` container's arq process
connects to Redis and registers `healthcheck`.

## Explicitly untouched

Per the directive's "delete old code only as the equivalent new piece
lands" rule, the rest of the uncommitted Tools Registry work-in-progress
(`app/core/models/tools.py`, `tools_registry.py`'s non-meeting-room slots,
`tools_service.py`, `tools_router.py`, `tools_schemas.py`, and the
`b2c3d4e5f6a7_add_tool_columns_to_permission.py` migration) is left in
place. It gets superseded once the `plugins` schema (ADR-0003) is
designed and built, not before.

## Google STT — forward-looking input, not acted on

`E:\googleSTT` (outside this repo) is the user's scratch venv for
evaluating Google Speech-to-Text: `google-cloud-speech` 2.40.0, a
service-account key, a sample Hindi audio clip, no integration code yet.
Two things to remember when the Meeting Room live-captions phase reaches
this:

1. The service-account JSON must **never** be committed to this repo —
   load it via `GOOGLE_APPLICATION_CREDENTIALS` pointing at a path outside
   the repo, or eventually via the same Fernet-encrypted-at-rest secrets
   envelope pattern the directive requires for provider credentials.
2. Google STT is now the **only** wired STT/TTS backend
   (`_google_stt`/`_google_tts` in `live_agents/providers.py`), so this is
   a credentials/config step (set `GOOGLE_APPLICATION_CREDENTIALS`, flip
   `LIVE_AGENTS_CAPTIONS_ENABLED=true`), not new architecture.

## Open questions

- **Dockerfile Python version**: pinned to `python:3.11-slim`; the old
  README said "Python 3.10+" and the local dev `.venv` is actually 3.10 —
  confirm 3.11 is fine for the containerized path or align it with 3.10.
- **Compose DSN override mechanism**: `backend`/`worker` override
  `DATABASE_URL`/`REDIS_URL` via an `environment:` block layered on top of
  `env_file: ./backend/.env`, so the in-network services reach `postgres`/
  `redis` by service name while `.env` stays the source of truth for bare
  local dev. Revisit if a real `.env.docker` split becomes worth it.
- **`tasking` schema's fate** (ADR-0003): unresolved, deferred to the
  core-schema-&-auth phase.
- **`plugins` vs `core` Tools Registry successor boundary** (ADR-0003):
  whether the non-meeting-room slots (`whatsapp_send`, `reply_generator`,
  `comms_agent`, `video_provider`) become plugin entitlements or stay
  simpler `core` config — unresolved.
- **Sinhala Google Cloud TTS voice**: unresolved, see the trim section
  above.

## Roadmap

Prompt 2 — Core schema & auth. Prompt 3 — WhatsApp service. Prompt 4 —
Meeting Room + plugin entitlements. Prompt 5 — Staff observability &
WhatsApp test console. Prompt 6 — Frontend: three dashboards. Prompt 7 —
Hardening pass. Each is planned and executed as its own separate session,
per the rebuild directive.
