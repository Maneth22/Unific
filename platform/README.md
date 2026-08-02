# UNIFIC Platform

UNIFIC is an eight-room operating system for running client-facing community
programs: staff manage clients, clients manage a tree of community
identities, and community members are reached over WhatsApp with
AI-assisted translation, tone analysis, and reply drafting — with every
dollar, message, and permission traceable back to the room and identity
that produced it.

Three of the eight rooms are built and load-bearing today: **Accounts**
(Task 1), **Profiles** (Task 2), and **Meeting Room** (Task 3, renamed from
"Communications"). A fourth, **Initial Tasking** (Task 4), exists in a
narrower internal-only form — see [Room status](#room-status). This README
is the system-level map; `docs/ARCHITECTURE.md` is the detailed room
contract new rooms must follow. As more rooms are built, expect pieces of
this document to be promoted into their own files under `docs/` — this is
written to make that split easy later, not to replace it.

## Contents

- [System overview](#system-overview)
- [The eight rooms](#the-eight-rooms)
- [Shared core infrastructure (the room contract)](#shared-core-infrastructure-the-room-contract)
- [Identity tree & permissions (Task 2)](#identity-tree--permissions-task-2)
- [Who can do what](#who-can-do-what)
- [The Meeting Room pipeline](#the-meeting-room-pipeline)
- [External providers](#external-providers)
- [AI usage tracking](#ai-usage-tracking)
- [Security boundaries](#security-boundaries)
- [Project layout](#project-layout)
- [Local development setup](#local-development-setup)
- [Configuration reference](#configuration-reference)
- [Running tests](#running-tests)
- [Further documentation](#further-documentation)

## System overview

```
                         ┌───────────────────────────┐
                         │        Postgres 16         │
                         │  one schema per room, plus  │
                         │  a shared `core` schema     │
                         └──────────────▲──────────────┘
                                        │ async SQLAlchemy 2.0
                         ┌──────────────┴──────────────┐
                         │        FastAPI backend       │
                         │   app/main.py mounts one      │
                         │   router per room + auth      │
                         └──────────────▲──────────────┘
                                        │ REST (JSON, cookie/JWT auth)
         ┌──────────────────────────────┼──────────────────────────────┐
         │                              │                              │
┌────────┴────────┐          ┌──────────┴──────────┐         ┌─────────┴─────────┐
│  Staff dashboard │          │  Client dashboard    │         │   Public / no-auth │
│  (React, /       │          │  (React, /client/*)  │         │   routes           │
│  and /portal)     │          │                      │         │                    │
│  Admin tier: all  │          │  Client owner: full  │         │  Client self-signup │
│  rooms + Staff &   │          │  org tree + billing  │         │  Community member   │
│  Access mgmt       │          │  Client staff: org   │         │  registration       │
│  Regular tier:     │          │  tree, no billing     │         │  WhatsApp webhook   │
│  own tasks + inbox │          │                      │         │  Meeting join link  │
└────────────────────┘          └──────────────────────┘         └────────────────────┘
                                        │
                         ┌──────────────┴──────────────┐
                         │      External providers      │
                         │  WhatsApp Cloud API (mock by  │
                         │  default) · Gemini (translate/│
                         │  reply/comms-agent) · LiveKit  │
                         │  (video conferencing)          │
                         └───────────────────────────────┘
```

**Stack**: FastAPI + async SQLAlchemy 2.0 + PostgreSQL 16 (backend), React +
Vite (frontend). WhatsApp, translation, LLM, and video-conferencing
integrations all sit behind provider interfaces (`app/core/providers/`)
with mock implementations selected by default — no live credentials are
required for local development; see [External providers](#external-providers).

**Two logins, three audiences.** Staff and clients never share a session:
the frontend mounts exactly one `AuthProvider` at a time depending on the
route subtree (`App.jsx`), and the backend issues JWTs with a distinct
`audience` claim per login type (`staff`, `client`, `client_staff`) so
route-gating is a type check on the token, not a role flag baked into
shared claims. Community members never log in at all — they are reached
purely through WhatsApp and a handful of unauthenticated public routes
(self-registration, invite links, meeting-join links).

## The eight rooms

| Task | Room | Status | Postgres schema |
|---|---|---|---|
| 1 | Accounts | Built | `accounts` |
| 2 | Profiles | Built | `profiles` |
| 3 | Meeting Room *(renamed from Communications)* | Built | `meeting_room` |
| 4 | Initial Tasking | Partially built — internal-only staff task/inbox tool lives at `app/tasking`, tagged `RoomName.initial_tasking`; the client-facing "tasking" concept from the original 8-room model is not built | `tasking` |
| 5 | Specialise | Not built | — |
| 6 | Resources | Not built | — |
| 7 | Assets | Not built | — |
| 8 | Hold Data | Not built — `core.ledger_entry` and `core.audit_log` stand in for it until then | — |

What each built (or partially built) room actually does:

- **Accounts** — the Account Registry (external service credentials,
  Fernet-encrypted, revealed only through an audited admin-only call),
  financial records, API health monitoring, the AI-usage summary view, and
  each room's Archive Locker / spend dashboard rolled up for staff.
- **Profiles** — the identity tree (`profiles.identity`): clients, their
  community groups, and individual members, plus permissions, profile
  accounts (credit balances), consent records, the staff directory, and
  the client self-registration / group-invite / member-registration flows
  described below.
- **Meeting Room** — one 1:1 WhatsApp-backed conversation per identity,
  the AI comms pipeline (clarify / translate / tone-analyze / reply-draft),
  session and satisfaction reports, community-member summaries, scheduled
  meetings with LiveKit video conferencing, and the room's own Archive
  Locker.
- **Initial Tasking** *(internal, not the client-facing Task 4 concept
  yet)* — admin-assigned staff tasks with an append-only progress/concern
  log, and a shared inbox for staff↔staff, staff↔admin, and staff↔client
  notices.

A `staff_directory` module (admin-managed staff categories + the staff
list) backs the Profiles Room's "Staff" tab; it isn't a room itself —
staff accounts are deliberately never nodes in the identity tree.

## Shared core infrastructure (the room contract)

Every room — built or future — shares four things that live once in
`app/core` and are never duplicated per room:

1. **Its own Postgres schema** for room-specific business data. Every
   model sets `__table_args__ = {"schema": "<room>"}`; new model modules
   register in `alembic/env.py`'s import loop and mount a router in
   `app/main.py`.
2. **A view onto one master calendar** — `core.services.calendar_service`.
   A room submits its own timing rather than keeping a private calendar.
3. **An Archive Locker** — `core.services.archive_service`, operating on
   `core.archive_item` rows tagged by room, with three shelves
   (Operational Library, Transfer, Receiving) and a four-step, fully
   audited transfer/accept flow. A room's "locker" is just the set of
   `ArchiveItem` rows where `room = <that room>`.
4. **A room account with one sub-account per agent** —
   `core.services.spend_service`, so UNIFIC's own operating cost stays
   traceable to the agent that incurred it (`scripts/seed_rooms.py` seeds
   these up front).

A fifth piece is cross-room by design: **the gate**,
`core.services.gate_service.check_and_charge()`. Anything a room does out
of its own Shelf 1 content (e.g. an auto-reply) is UNIFIC's own running
cost. Anything that should draw on a *member's* balance instead must call
`check_and_charge()` first — it reads the identity's effective permissions
and profile-account balance, then debits and ledgers the charge. No room
should ever spend an identity's credit without going through this
function.

See `docs/ARCHITECTURE.md` for the full contract, including how a new
room (Tasks 5–8) should be wired up to match.

## Identity tree & permissions (Task 2)

`profiles.identity` is a self-referencing tree — Group → Group → … →
Member, arbitrary depth — representing a client org, its community
groups, and individual community members. Scope checks walk a
materialized `path` column rather than Postgres's `ltree` extension (a
deliberate substitution; see `docs/ARCHITECTURE.md`).

Permissions only ever narrow going down the tree, and are **precomputed,
not merged live**: `profiles.permission.effective_*` is recalculated
top-down any time a node's own permissions change or a subtree moves
(booleans AND with the parent, ranked scopes take the MIN, credit caps
take the MIN) — so a bad write can never produce an effective value wider
than the parent allows. Anything reading permissions should read
`effective_*`, never walk ancestors itself.

Four client-facing flows sit on top of this tree: client self-registration
+ admin approval, client-created community groups, revocable public
group-invite links, and instant public member registration ending in a
`wa.me` deep link into WhatsApp. None of these involve group chat — every
member still gets the same individual 1:1 conversation every identity has
always gotten (see `docs/ARCHITECTURE.md` for why group-session fan-out is
paused).

## Who can do what

| Actor | Login | JWT audience | Scope |
|---|---|---|---|
| Staff — Admin | `/login` | `staff` | Every room, every identity; Staff & Access management, registration-request approval |
| Staff — regular | `/login` | `staff` | Own assigned tasks + inbox only (`/portal`), no client or cost data |
| Client — owner/co-owner | `/client/login` | `client` | Their own org subtree: communities, members, meetings, billing/funding |
| Client — org staff | created by a client owner | `client_staff` | Same org subtree read/write, **blocked** from money and from managing other client-staff/co-owner logins |
| Community member | none — WhatsApp only | — | Reached via their linked WhatsApp number; onboarded via public invite/registration links |
| Public (unauthenticated) | none | — | Client signup, member registration, meeting-join links, the WhatsApp webhook |

Client-side scope is enforced by `app.profiles.security.require_identity_scope()`
on every request (checks the target identity is the caller's own root or a
descendant of it) — never by hiding a nav item in the frontend.

## The Meeting Room pipeline

Each identity has one 1:1 WhatsApp-backed `Conversation`. Inbound
messages and outbound replies pass through `CommsAgent`
(`core/providers/base.py`), selected via `COMMS_AGENT_PROVIDER=gemini|mock`:

- **clarify_inbound** — detects language and produces a clear-English
  restatement the client's chat shows, with the raw original underneath.
- **analyze_tone** — proficiency / emotional tone / politeness / style +
  a one-line insight, per inbound message.
- **translate_outbound** — client English → the room's configured
  language, tone, and character voice (e.g. "Jake, a student volunteer"),
  using recent history so it auto-detects the member's language; facts
  (amounts, dates, promises) are prompted to survive translation.
- **generate_session_report** / **generate_satisfaction_analysis** — full
  transcript → a stored report the client can revisit for free.
- **generate_member_summary** — same transcript input, framed as an
  ongoing community-member profile, surfaced on the client dashboard's
  Profiles tab.

Every provider call in this pipeline is wrapped so a provider failure —
including an unconfigured Gemini key — degrades to a safe fallback
(untranslated text, a deterministic stub reply) instead of crashing the
pipeline.

**Meetings** are scheduled per identity and run on real-time video via
LiveKit (`VIDEO_PROVIDER=livekit`) — `MeetingInvite` mints join links with
a TTL, `MeetingParticipant` tracks who joined, and the frontend's
`VideoCallRoom` component drives the call. With no LiveKit credentials
set, a `MockVideoProvider` issues fake tokens so the join flow still works
end to end locally.

## External providers

`app/core/providers/factory.py` is the single place that reads which
implementation is selected — services depend only on the ABCs in
`base.py`, never on a concrete provider class. Every provider has a mock
(or stub) implementation so the app runs with zero external credentials.

| Provider | Env var | Real implementation | Mock/stub default |
|---|---|---|---|
| WhatsApp | `WHATSAPP_PROVIDER` | `cloud_api` — stubbed, not yet exercised against the live Cloud API | `mock` — logs sends, lets you simulate inbound messages from the Meeting Room's Chat tab |
| Translation | `TRANSLATION_PROVIDER` | `gemini` (default) | `mock` |
| Reply drafting | `REPLY_PROVIDER` | `gemini` (default) | `stub` — deterministic fallback text |
| Comms agent (clarify/tone/translate/reports) | `COMMS_AGENT_PROVIDER` | `gemini` (default) | `mock` |
| Video conferencing | `VIDEO_PROVIDER` | `livekit` | `mock` — fake room/token, no real media |

The Gemini-backed providers share one rate-limited client
(`gemini_client.py`) that retries transient 503/429s with backoff (the
free tier throws regular capacity errors). The reply generator is
prompt-constrained to only use Shelf-1 `context_snippets` it's given and
returns the deterministic fallback rather than guessing when nothing
relevant is found.

## AI usage tracking

Every real LLM call (reply drafting, translation, language detection)
writes one row to `core.llm_usage_record` — identity, room, agent, model,
action, token counts, and an estimated cost. Two read paths: the
Accounts Room's system-wide "AI Usage" tab
(`GET /api/accounts/ai-usage/summary`) and a per-identity history on the
Profiles Room (`GET /api/profiles/identities/{id}/ai-usage`).

**This is recording only — no spend cap is enforced yet.** The intended
hook is an `effective_token_limit_per_period` on `profiles.permission`,
checked alongside `gate_service.check_and_charge` before a provider call
proceeds; see `docs/ARCHITECTURE.md` for the exact wiring point.

## Security boundaries

- **Staff** are gated by `require_admin` (Admin tier) or `require_any_staff`
  (either tier) from `app.core.security.dependencies`, checked server-side
  on every request — there is no per-room grant table any more; any active
  Admin has every room.
- **Clients** are gated by `require_identity_scope()`; **client-staff**
  logins reuse the same scope check but are additionally blocked from
  billing and from managing other client-staff/co-owner logins via
  `require_client_owner`.
- **Every mutating route writes an audit row** (`core.audit_log`) with the
  real actor type and id — service functions take `actor_type`/`actor_id`
  as keyword args rather than hardcoding `ActorType.staff`, since several
  services (e.g. `create_identity`, `fund_identity`) are called from both
  staff and client routes.
- **Secrets** (`accounts.account_registry_entry.secret_ciphertext`) are
  Fernet-encrypted and only ever decrypted through an audited,
  staff-gated `reveal_secret` call — no room should read a raw secret
  value directly or assemble one into a provider/LLM payload.
- **Unauthenticated routes are the explicit minority**: the WhatsApp
  inbound webhook, client self-signup, and public member
  registration/invite-lookup routes. Every field from these is treated as
  untrusted input; the webhook additionally routes through
  `gate_service.check_and_charge` so an unlinked phone number is bounced
  immediately.

## Project layout

```
backend/app/
  core/           Shared infrastructure used by every room:
    models/         common enums (RoomName), archive, audit, calendar,
                     client/client-staff, ledger, llm_usage, room_account, staff
    providers/       WhatsApp / Translation / Reply / CommsAgent / Video
                     ABCs + mock and real (Gemini, LiveKit, Cloud API) implementations
    security/        JWT, cookies, password hashing, encryption, rate limiting
    services/        archive, audit, calendar, gate, llm_usage, pricing,
                     scope, spend — the room-contract primitives
  accounts/       Task 1 — Account Registry, financial records, API monitor
  profiles/       Task 2 — identity tree, permissions, consent, client
                  onboarding flows, public registration routes
  meeting_room/   Task 3 — conversations, messages, meetings, WhatsApp
                  links, session/satisfaction reports
  tasking/        Internal staff task assignment + shared inbox
  staff_directory/ Admin-managed staff categories + directory
  auth/           Staff login/session/bootstrap endpoints
frontend/src/
  rooms/          One folder per room's staff-dashboard screens
                  (accounts/, profiles/, meeting-room/)
  pages/          Top-level routed pages (staff, client, and public)
  api/            One module per room/audience's API client
  context/        AuthContext (staff) / ClientAuthContext (client, client-staff)
  routes/         ProtectedRoute / RequireAdmin / ScopeRoute guards
  layouts/        StaffDashboardLayout / StaffPortalLayout / ClientDashboardLayout
docs/ARCHITECTURE.md   the room contract — read before adding Task 4's
                        client-facing form, or Tasks 5–8
```

## Local development setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- Docker (for local Postgres) — or point `DATABASE_URL` at your own
  Postgres 16+ with the `ltree` extension available

### First-time setup

```bash
# 1. Start Postgres
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # then fill in JWT_SECRET / SECRETS_ENCRYPTION_KEY — see below
alembic upgrade head
python -m scripts.seed_rooms    # creates each room's account + agent sub-accounts
uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5183
```

Generate real local secrets rather than using the placeholders in
`.env.example`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"                    # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # SECRETS_ENCRYPTION_KEY
```

### First login

There is no self-registration for staff. Bootstrap the first (superadmin)
staff account once — this endpoint refuses to run again after the first
account exists:

```bash
curl -X POST http://localhost:8000/api/auth/staff/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.org","password":"a-strong-password-12+chars","full_name":"Your Name"}'
```

Log in at `http://localhost:5183/login`. As superadmin you have every
room; use **Staff & Access** in the sidebar to provision additional staff
and, from the Profiles Room, review and approve client signups.

### Local Postgres port

`docker-compose.yml` maps Postgres to host port **55432**, not the default
5432 — this machine may already have a native Postgres service bound to
5432 from another project. `DATABASE_URL` in `.env.example` already points
at 55432; adjust if your setup differs.

## Configuration reference

Everything below lives in `backend/.env` (copy from `.env.example`); no
external credentials are required to run the app locally.

| Group | Key | Notes |
|---|---|---|
| Database | `DATABASE_URL` | asyncpg URL; defaults to the docker-compose Postgres on port 55432 |
| JWT | `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | generate a real secret, see above |
| Secrets envelope | `SECRETS_ENCRYPTION_KEY` | Fernet key used by the Account Registry's credential encryption |
| CORS / links | `CORS_ORIGINS`, `FRONTEND_BASE_URL` | `FRONTEND_BASE_URL` must match the Vite dev port (5183), used to build links like community invite URLs |
| WhatsApp deep link | `WHATSAPP_AGENT_DISPLAY_NUMBER` | shown as a `wa.me` link after public member registration |
| Login protection | `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` | |
| Providers | `WHATSAPP_PROVIDER`, `TRANSLATION_PROVIDER`, `REPLY_PROVIDER`, `COMMS_AGENT_PROVIDER`, `VIDEO_PROVIDER` | see [External providers](#external-providers) |
| WhatsApp Cloud API | `WHATSAPP_CLOUD_API_TOKEN`, `WHATSAPP_CLOUD_API_PHONE_NUMBER_ID`, `WHATSAPP_CLOUD_API_VERIFY_TOKEN` | only used when `WHATSAPP_PROVIDER=cloud_api` |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_RATE_LIMIT_DELAY`, `GEMINI_MAX_CONCURRENT` | get a key at https://aistudio.google.com/apikey |
| LiveKit | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `MEETING_INVITE_TTL_HOURS`, `MEETING_TOKEN_TTL_MINUTES` | get credentials at https://cloud.livekit.io |
| Environment | `ENVIRONMENT` | `development` by default; the video-provider factory logs a hard error if a production boot has no real `VIDEO_PROVIDER` configured |

To wire up real WhatsApp later, set `WHATSAPP_PROVIDER=cloud_api` and fill
in the Cloud API vars — no application code changes are needed (see
`app/core/providers/cloud_api_whatsapp.py`).

## Running tests

```bash
cd backend
pytest tests/ -v
```

Tests run against the same database as `DATABASE_URL` (there is no
separate test database yet) — they clean up the rows they create.

## Further documentation

- `docs/ARCHITECTURE.md` — the room contract in full detail: exact service
  entry points, the security-boundary rationale, provider-interface
  conventions, and what Task 8 (Hold Data) will eventually absorb. Read
  this before building Task 4's client-facing form or Tasks 5–8.
- This README is the intended jumping-off point if/when the system grows
  a dedicated `docs/` site — the sections above are scoped so each can be
  lifted into its own page (e.g. a per-room doc, a security doc, a
  provider-integration doc) without needing to be rewritten from scratch.
