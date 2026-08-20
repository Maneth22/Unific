# UNIFIC Platform — Database Schema

One physical Postgres database, five schemas: `core`, `accounts`,
`profiles`, `meeting_room`, `tasking`. The schema boundary is what makes a
"room" (see `ARCHITECTURE.md`) — each room's business data lives in its own
schema, while four pieces of shared infrastructure (calendar, archive,
room-account/spend, staff/client identity) live once in `core` and are
reused by every room rather than duplicated per room.

Every model sets its schema explicitly via `__table_args__ = {"schema":
"<name>"}` (`app/database.py`); nothing relies on Postgres's default
`search_path`. All tables share one `DeclarativeBase` (`app.database.Base`)
and one `MetaData` naming convention, so Alembic autogenerate produces
stable, diffable constraint names across every schema:

| Constraint kind | Pattern |
|---|---|
| Index | `ix_%(column_0_label)s` |
| Unique | `uq_%(table_name)s_%(column_0_name)s` |
| Check | `ck_%(table_name)s_%(constraint_name)s` |
| Foreign key | `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` |
| Primary key | `pk_%(table_name)s` |

Migrations live in `platform/backend/alembic/versions/`; the Alembic
version table itself is pinned to the `core` schema
(`version_table_schema="core"` in `alembic/env.py`). `alembic/env.py`
imports every room's `models.py` in a loop so `Base.metadata` is fully
populated before autogenerate runs — a room that doesn't exist yet is
simply skipped (`ModuleNotFoundError`), so this file never needs editing
when a new room is added.

Primary keys are almost always a `String` UUID (`default=uuid_str`, see
`app/core/models/common.py`) rather than a Postgres-native `uuid` column —
kept as plain strings so every layer (Python, JSON payloads, JS on the
frontend) handles them identically. A handful of high-volume/append-only
tables (`ledger_entry`, `message`, `login_attempt`) use an autoincrementing
`Integer` PK instead, since nothing ever needs to reference those rows by a
pre-generated id before insert. Two junction-style tables
(`permission`, `profile_account`) use their owning `identity_id` directly
as the primary key (1:1 with `identity`, no separate surrogate key).

All timestamps are naive UTC `DateTime` columns (`utcnow()` in
`common.py` strips tzinfo after computing UTC) — never `TIMESTAMPTZ`, and
never a timezone-aware Python value going into the DB.

---

## Schema map

| Schema | Room (Task #) | Purpose |
|---|---|---|
| `core` | shared infra | Staff/client login, the identity-tree-agnostic audit log, the one financial ledger, the one calendar, the archive locker, room accounts, LLM usage, webhook traffic, the tools registry |
| `accounts` | 1 — Accounts | Account Registry (every external account UNIFIC uses), manual Financial Dashboard entries, API Monitor |
| `profiles` | 2 — Profiles | The identity tree (Groups → Members), permissions cascade, token-credit accounts, consent records, registration invites/roster |
| `meeting_room` | 3 — Meeting Room | WhatsApp conversations/messages, live video meetings, participants, invites, phone↔identity links, session reports, in-call chat |
| `tasking` | 4 — Initial Tasking | Internal staff task assignment/progress and a staff↔staff/staff↔client inbox |

Tasks 5–8 (`specialise`, `resources`, `assets`, `hold_data`) are reserved
in `RoomName` (`app/core/models/common.py`) but have no schema or tables
yet — they'll follow the identical room-contract shape described in
`ARCHITECTURE.md` when built.

---

## `core` schema

### `staff_user`
A UNIFIC staff account (`app/core/models/staff.py`).

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `email` | String(255) | unique, indexed |
| `password_hash` | String(255) | |
| `full_name` | String(255) | |
| `tier` | Enum `staff_tier` (`admin`, `staff`) | default `staff`; the only access-relevant field — `admin` sees everything, `staff` is limited to their own tasks/updates/inbox |
| `category_id` | String, FK → `core.staff_category.id` (SET NULL) | nullable, indexed |
| `is_active` | Boolean | default true |
| `mfa_secret` | String(255) | nullable; reserved for future TOTP MFA, not enforced yet |
| `mfa_enabled` | Boolean | default false |
| `created_at` / `updated_at` | DateTime | |

### `staff_category`
Admin-managed organizational label for staff accounts (e.g. "Developer",
"Marketing") — no access implications.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `name` | String(100) | unique |
| `description` | Text | default `""` |
| `created_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_at` | DateTime | |

### `refresh_token`
One row per issued rotating/revocable refresh token, shared across all
three login flows (staff, client, client-staff) rather than duplicated per
audience.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `token_hash` | String(255) | unique, indexed |
| `staff_user_id` | String, FK → `core.staff_user.id` (CASCADE) | nullable, indexed |
| `client_user_id` | String | nullable, indexed — **not** an FK (client tables live logically alongside, see below) |
| `client_staff_user_id` | String | nullable, indexed — not an FK |
| `issued_at` | DateTime | |
| `expires_at` | DateTime | |
| `revoked_at` | DateTime | nullable |
| `replaced_by_id` | String | nullable — points at the token that rotated this one out |

### `login_attempt`
Rate-limiting/lockout log, keyed by login identifier (email).

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK, autoincrement | |
| `identifier` | String(255) | indexed |
| `success` | Boolean | |
| `ip_address` | String(64) | nullable |
| `created_at` | DateTime | indexed |

### `client_user`
A full-access, org-scoped login — the org owner (or a co-owner an admin
provisions later; `is_owner` is a display/audit label only, every row has
identical access). Always scoped to exactly one `profiles.identity` root.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `email` | String(255) | unique, indexed |
| `password_hash` | String(255) | |
| `full_name` | String(255) | |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `is_owner` | Boolean | default true |
| `is_active` | Boolean | default true |
| `created_at` / `updated_at` | DateTime | |

### `client_staff_user`
A narrower, org-scoped login a `client_user` creates for their own
employees. Mirrors `client_user`'s shape as a separate table (own JWT
audience `client_staff`) — not a role flag. Full read/write on ILC groups,
members, and meetings under the org; blocked from money and from managing
other client-staff/co-owner logins.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `email` | String(255) | unique, indexed |
| `password_hash` | String(255) | |
| `full_name` | String(255) | |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `created_by_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `is_active` | Boolean | default true |
| `created_at` / `updated_at` | DateTime | |

### `client_registration_request`
A pending organisation signup, staged separately from `client_user`
(which requires a non-null `identity_id` that doesn't exist yet at signup
time). No DB-level unique constraint on `email` — a rejected org may
resubmit; the service layer checks for duplicates itself.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `org_name` | String(255) | |
| `contact_name` | String(255) | |
| `email` | String(255) | indexed, not unique |
| `password_hash` | String(255) | |
| `status` | Enum `client_registration_status` (`pending`, `approved`, `rejected`) | default `pending` |
| `rejection_reason` | Text | default `""` |
| `reviewed_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `reviewed_at` | DateTime | nullable |
| `created_client_user_id` | String, FK → `core.client_user.id` (SET NULL) | nullable — set on approval |
| `created_at` / `updated_at` | DateTime | |

Approval (`app.profiles.services.approve_client_registration`) atomically
creates the org's root `profiles.identity` (Group, named `org_name`) and
the real `client_user` bound to it, then stamps this row `approved`.

### `audit_log`
The append-only audit trail for **every** mutating action across every
room (logins, permission changes, secret reveals, sends) — financial or
not. Distinct from `ledger_entry` (money movements only) and from
`webhook_log` (raw wire payloads only).

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `actor_type` | Enum `actor_type` (`staff`, `client`, `client_staff`, `system`) | not null |
| `actor_id` | String | nullable, indexed |
| `action` | String(255) | not null, indexed |
| `room` | Enum `room_name` | nullable |
| `entity_type` | String(100) | nullable |
| `entity_id` | String | nullable, indexed |
| `before` / `after` | JSONB | nullable — snapshots for diffing; may hold `Decimal` values (serialized to string via a custom JSON encoder in `app/database.py`) |
| `note` | Text | default `""` |
| `ip_address` | String(64) | nullable |
| `created_at` | DateTime | not null, indexed |

### `ledger_entry`
The **one** append-only financial ledger. Every token movement anywhere in
the system — funding, agent spend, gate charges, adjustments — writes one
row here; nothing else keeps its own private ledger.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK, autoincrement | |
| `entry_type` | Enum `ledger_entry_type` (`funding`, `customer_transfer`, `agent_spend`, `gate_charge`, `adjustment`) | indexed |
| `room` | Enum `room_name` | not null, indexed |
| `agent_name` | String(100) | nullable — set for `agent_spend` rows |
| `identity_id` | String, FK → `profiles.identity.id` (SET NULL) | nullable, indexed |
| `amount` | Numeric(18,6) | not null |
| `balance_after` | Numeric(18,6) | nullable |
| `description` | Text | default `""` |
| `audit_log_id` | String, FK → `core.audit_log.id` (SET NULL) | nullable |
| `created_at` | DateTime | indexed |

### `room_account`
One token-credit account per room (Task 1's room-contract piece #4). A
room's *own* operating cost, distinct from any identity's
`profiles.profile_account` balance.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `room` | Enum `room_name` | unique (one account per room) |
| `balance` | Numeric(18,6) | default 0 |
| `created_at` / `updated_at` | DateTime | |

Relationship: `room_account.agent_sub_accounts` → `agent_sub_account`
(cascade delete-orphan).

### `agent_sub_account`
One sub-account per agent within a room's account, so spend is always
traceable to the agent that incurred it.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `room_account_id` | String, FK → `core.room_account.id` (CASCADE) | not null |
| `agent_name` | String(100) | not null |
| `balance` | Numeric(18,6) | default 0 |
| `created_at` / `updated_at` | DateTime | |

Unique index: `(room_account_id, agent_name)`.

### `calendar_event`
The one master calendar (Task 1's Calendar Engine). Every room submits its
own timing rows here instead of keeping a private calendar.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `room` | Enum `room_name` | not null, indexed |
| `kind` | String(100) | not null |
| `title` | String(255) | not null |
| `description` | Text | default `""` |
| `due_at` | DateTime | not null, indexed |
| `remind_at` | DateTime | nullable, indexed |
| `reminder_fired` | Boolean | default false |
| `related_entity_type` | String(100) | nullable |
| `related_entity_id` | String | nullable |
| `is_resolved` | Boolean | default false |
| `created_at` / `updated_at` | DateTime | |

### `archive_item`
The three-shelf Archive Locker, shared by every room. A room's "locker" is
not a separate table — it's the set of rows where `room = <that room>`.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `room` | Enum `room_name` | not null, indexed |
| `shelf` | Enum `archive_shelf` (`operational_library`, `transfer`, `receiving`) | not null, indexed |
| `status` | Enum `archive_item_status` (`draft`, `approved`, `received`, `reviewed`, `accepted`, `rejected`, `active`) | default `active` |
| `title` | String(255) | not null |
| `description` | Text | default `""` |
| `item_type` | String(100) | default `"document"` |
| `content` | JSONB | default `{}` |
| `source_room` | Enum `room_name` | nullable — for a Receiving-shelf item, which room sent it |
| `target_room` | Enum `room_name` | nullable — for an outbound-approved item, which room it's bound for |
| `approved_for_auto_reply` | Boolean | default false — true only for accepted/active Operational Library items the Meeting Room's auto-reply may draw from |
| `version` | Integer | default 1 |
| `reviewed_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `reviewed_at` | DateTime | nullable |
| `created_at` / `updated_at` | DateTime | |

Shelf transitions (`propose_transfer` → `deliver` → `review` →
`accept`/`reject`) are four distinct, audited steps — nothing is
auto-accepted from Receiving into Shelf 1.

### `llm_usage_record`
One row per LLM provider call, keyed to the triggering identity —
supports per-user usage totals and a future spend cap check.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `room` | Enum `room_name` | not null, indexed |
| `agent_name` | String(100) | not null |
| `identity_id` | String, FK → `profiles.identity.id` (SET NULL) | nullable, indexed |
| `provider` | String(50) | not null |
| `model` | String(100) | not null |
| `action` | String(50) | not null — e.g. `reply_generation`, `translation`, `language_detection` |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | Integer | nullable |
| `estimated_cost` | Numeric(18,6) | nullable |
| `created_at` | DateTime | indexed |

### `webhook_log`
Raw inbound/outbound webhook traffic, logged unconditionally — the ground
truth for what a provider actually sent/received, distinct from
`audit_log` (actions taken) and `meeting_room.message` (only successfully
parsed messages). A malformed/rejected payload still gets a row here.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `room` | Enum `room_name` | not null |
| `provider` | String(100) | not null |
| `direction` | Enum `webhook_direction` (`inbound`, `outbound`) | not null |
| `raw_payload` | JSONB | not null |
| `status` | Text | not null |
| `created_at` | DateTime | indexed |

### `tool_catalog_entry`
Admin-visible metadata for the Tools Registry — which concrete service
implementation exists for each pluggable slot (WhatsApp sender, reply
generator, comms agent, video provider, meeting STT/TTS/translation).
Deliberately **not** what decides whether a `tool_key` actually works
(that's the code-level `_REGISTRY` in `app.core.services.tools_registry`);
package version is never stored, only read live via `importlib.metadata`.

| Column | Type | Notes |
|---|---|---|
| `slot` | Enum `tool_slot` (`whatsapp_send`, `reply_generator`, `comms_agent`, `video_provider`, `meeting_stt`, `meeting_tts`, `meeting_translation`) | **PK part 1** |
| `tool_key` | String(100) | **PK part 2** — not globally unique alone; a key like `"gemini"` is valid under multiple slots |
| `display_name` | String(200) | not null |
| `description` | Text | default `""` |
| `package_name` | String(200) | nullable |
| `is_enabled` | Boolean | default true — staff off-switch; disabling doesn't force-migrate existing selections |
| `created_at` / `updated_at` | DateTime | |

### `tool_global_selection`
The staff-editable, system-wide default tool per slot (and, for the two
per-language slots, per language). For `whatsapp_send`/`video_provider`
(singleton platform infra) this is the *only* selection that ever exists;
for the other five slots it's the root-of-cascade default that
`profiles.permission`'s `own_*`/`effective_*` columns cascade from.

| Column | Type | Notes |
|---|---|---|
| `slot` | Enum `tool_slot` | **PK part 1** |
| `language` | String(20) | **PK part 2** — literal `"*"` (`GLOBAL_LANGUAGE`) for single-choice slots, ISO 639-1 code for `meeting_stt`/`meeting_tts` |
| `tool_key` | String(100) | not null |
| `voice` | String(200) | nullable — only meaningful for `slot=meeting_tts` (provider-specific voice id) |
| `updated_at` | DateTime | |
| `updated_by_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |

---

## `accounts` schema (Task 1)

### `account_registry_entry`
Every external account UNIFIC uses.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `name` | String(255) | not null |
| `category` | Enum `account_category` (`ai_platform`, `comms_platform`, `payment`, `hosting`, `domain`, `government`, `banking`, `tool`, `other`) | not null |
| `provider` | String(255) | default `""` |
| `purpose` | Text | default `""` |
| `owner` | String(255) | default `""` |
| `renewal_date` | Date | nullable |
| `linked_api` | String(255) | default `""` |
| `documentation_url` | String(1000) | default `""` |
| `secret_ciphertext` | Text | nullable — Fernet-encrypted at rest, only decrypted via the explicit `reveal` action; never sent to an LLM |
| `created_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_at` / `updated_at` | DateTime | |

### `financial_record`
A manual expense entry (salaries, contractor invoices, subscriptions).
Automatic agent API spend is recorded separately, into `core.ledger_entry`
— the Financial Dashboard reads both.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `category` | Enum `financial_record_category` (`subscription`, `salary`, `contractor`, `api_usage`, `hosting`, `other`) | not null |
| `description` | String(500) | not null |
| `amount` | Numeric(18,2) | not null |
| `currency` | String(10) | default `"AUD"` |
| `incurred_at` | Date | not null |
| `recurring` | Boolean | default false |
| `recurrence_period` | String(50) | default `""` |
| `linked_account_registry_id` | String, FK → `accounts.account_registry_entry.id` (SET NULL) | nullable |
| `created_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_at` | DateTime | |

### `api_monitor_entry`
Live health/usage tracking per external API.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `service_name` | String(255) | not null |
| `linked_account_registry_id` | String, FK → `accounts.account_registry_entry.id` (SET NULL) | nullable |
| `credit_remaining` | Numeric(18,6) | nullable |
| `usage_current_period` | Numeric(18,6) | nullable |
| `monthly_limit` | Numeric(18,6) | nullable |
| `health_status` | Enum `api_health_status` (`healthy`, `degraded`, `down`, `unknown`) | default `unknown` |
| `last_checked_at` | DateTime | nullable |
| `notes` | Text | default `""` |
| `created_at` / `updated_at` | DateTime | |

---

## `profiles` schema (Task 2)

### `identity`
The ID registry — a self-referencing tree (Group → Group → … → Member,
arbitrary depth). Every other schema's identity-scoped rows point here.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `parent_id` | String, FK → `profiles.identity.id` (RESTRICT) | nullable, indexed |
| `id_type` | Enum `identity_type` (`group`, `member`) | not null — a `member` is always a leaf, enforced in the service layer, not the DB |
| `name` | String(255) | not null |
| `path` | Text | not null, **unique** — materialized path (dot-joined ancestor ids); B-tree index with `text_pattern_ops` for O(log n) prefix (ancestor/descendant) scope checks, standing in for `ltree` (see file docstring for why) |
| `is_active` | Boolean | default true |
| `created_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_by_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `created_at` / `updated_at` | DateTime | |

`created_by`/`created_by_client_id` are best-effort convenience columns
(both null for public self-registration); `core.audit_log` is the actual
source of truth for "who did this."

One-to-one children (each `cascade="all, delete-orphan"` on the `identity`
side): `permission`, `profile_account`, `member_profile`,
`client_org_profile`, `ilc_group_profile`.

### `permission`
One row per identity — the narrowing-inheritance cascade every access
check reads. `own_*` is this identity's explicit override (`null` =
inherit from parent); `effective_*` is precomputed by
`app.core.services.permission_cascade` and is what every read path
(including the WhatsApp message gate) actually uses.

| Column | Type | Notes |
|---|---|---|
| `identity_id` | String PK, FK → `profiles.identity.id` (CASCADE) | |
| `own_registered` / `own_connected` / `own_auto_respond` / `own_send_on` | Boolean | nullable |
| `own_can_message_scope` / `own_can_receive_scope` | Enum `permission_scope` (`none`, `within_tree`, `any`) | nullable |
| `own_credit_cap` | Numeric(18,6) | nullable |
| `own_daily_reply_cap` | Integer | nullable — max WhatsApp auto-replies/day (UTC); enforced in `whatsapp_community.orchestrator`, not here |
| `own_reply_role` / `own_reply_tone` / `own_reply_complexity` / `own_reply_character` | String(100) | nullable |
| `own_reply_language` | String(20) | nullable |
| `own_reply_generator_tool` / `own_comms_agent_tool` / `own_meeting_translation_tool` | String(100) | nullable — Tools Registry per-identity override |
| `own_meeting_stt_tools` / `own_meeting_tts_tools` | JSONB | nullable — `{language: tool_key}` maps, merged key-by-key not replaced wholesale |
| `consent_required` | Boolean | not null |
| `effective_registered` | Boolean | default true |
| `effective_connected` | Boolean | default false |
| `effective_auto_respond` | Boolean | default false |
| `effective_send_on` | Boolean | default true |
| `effective_can_message_scope` / `effective_can_receive_scope` | Enum `permission_scope` | default `within_tree` |
| `effective_credit_cap` | Numeric(18,6) | nullable |
| `effective_daily_reply_cap` | Integer | nullable |
| `effective_reply_role` | String(100) | default `"member"` |
| `effective_reply_tone` | String(100) | default `"friendly"` |
| `effective_reply_complexity` | String(100) | default `"standard"` |
| `effective_reply_character` | String(100) | default `"assistant"` |
| `effective_reply_language` | String(20) | default `"en"` |
| `effective_reply_generator_tool` | String(100) | default `"stub"` |
| `effective_comms_agent_tool` | String(100) | default `"gemini"` |
| `effective_meeting_translation_tool` | String(100) | default `"gemini"` |
| `effective_meeting_stt_tools` / `effective_meeting_tts_tools` | JSONB | default `{}` |
| `updated_at` | DateTime | |

`whatsapp_send`/`video_provider` have no `own_*`/`effective_*` columns at
all — both are singleton platform infra (one WhatsApp Business number, one
LiveKit deployment), never identity-scoped; see `core.tool_global_selection`.

### `profile_account`
One token-credit account per identity. Funding/spend always writes a
`core.ledger_entry` row in the same transaction.

| Column | Type | Notes |
|---|---|---|
| `identity_id` | String PK, FK → `profiles.identity.id` (CASCADE) | |
| `balance` | Numeric(18,6) | default 0 |
| `updated_at` | DateTime | |

### `consent_record`
Append-only consent log.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `context` | Enum `consent_context` (`onboarding`, `record_time`) | not null |
| `granted` | Boolean | not null |
| `retention_period` | String(100) | default `""` |
| `data_residency` | String(100) | default `""` |
| `note` | Text | default `""` |
| `captured_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `granted_at` | DateTime | |

### `group_invite`
A public registration link for one Group identity (e.g. a client's
community). At most one `is_active` row per `identity_id` — regenerating
deactivates the current row and inserts a new one (rotate, not mutate) so
a leaked link goes cold and full issuance history is kept.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `token` | String(64) | unique, indexed |
| `is_active` | Boolean | default true |
| `created_by_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `created_by_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_at` | DateTime | |

Partial unique index `uq_group_invite_active_identity` on `identity_id`
`WHERE is_active`.

### `member_profile`
Descriptive info collected by the public member-registration form (name
lives on `Identity.name`; this holds the rest). Deliberately duplicates
`phone_number` with `meeting_room.whatsapp_link` — that table is the
operational routing record the message pipeline reads; this one is the
descriptive record the client dashboard reads.

| Column | Type | Notes |
|---|---|---|
| `identity_id` | String PK, FK → `profiles.identity.id` (CASCADE) | |
| `email` | String(255) | default `""` |
| `phone_number` | String(32) | not null |
| `extra_info` | JSONB | default `{}` — named to avoid colliding with SQLAlchemy's `Base.metadata` |
| `registered_at` | DateTime | |
| `registered_via` | String(50) | default `"public_form"` |
| `source_invite_id` | String, FK → `profiles.group_invite.id` (SET NULL) | nullable |
| `ilc_roster_entry_id` | String, FK → `profiles.ilc_member_roster.id` (SET NULL) | nullable — which pre-issued roster row this registration was verified against, set once, never reassigned |
| `updated_at` | DateTime | |

### `group_code_sequence`
Backs system-issued, human-readable Group IDs (`CLI-000001`,
`ILC-000001`) — one row per prefix, incremented atomically
(`UPDATE ... SET next_value = next_value + 1 RETURNING next_value`) so
concurrent creates never collide.

| Column | Type | Notes |
|---|---|---|
| `prefix` | String(16) PK | e.g. `"CLI"`, `"ILC"` |
| `next_value` | Integer | default 1 |

### `client_org_profile`
Client-organization-only fields, 1:1 with the org's root `identity`.

| Column | Type | Notes |
|---|---|---|
| `identity_id` | String PK, FK → `profiles.identity.id` (CASCADE) | |
| `group_code` | String(32) | unique, not null |
| `entity_type` | String(255) | default `""` |
| `role_description` | Text | default `""` |
| `abn_acnc_number` | String(64) | nullable |
| `created_at` / `updated_at` | DateTime | |

### `ilc_group_profile`
ILC-community-group-only fields, 1:1 with the group's `identity`.

| Column | Type | Notes |
|---|---|---|
| `identity_id` | String PK, FK → `profiles.identity.id` (CASCADE) | |
| `group_code` | String(32) | unique, not null |
| `name_hindi` | String(255) | default `""` — `Identity.name` already holds the English name |
| `registration_number` | String(100) | default `""` |
| `date_of_registration` | Date | nullable |
| `application_signed` | Boolean | default false |
| `registered_office` | Text | default `""` |
| `area_of_operation` | Text | default `""` |
| `governing_act` | String(255) | default `""` |
| `registering_authority` | String(255) | default `""` |
| `objective` | Text | default `""` |
| `cooperative_type` | String(255) | default `""` |
| `bank_account` | String(100) | default `""` |
| `created_at` / `updated_at` | DateTime | |

### `ilc_member_roster`
A client-assigned, pre-issued ILC registration number for one community
group — the allow-list the public member-registration form checks
against. Unrecognized numbers are rejected outright; an already-claimed
number is rejected as a duplicate.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `group_identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `ilc_registration_number` | String(64) | not null |
| `is_claimed` | Boolean | default false |
| `claimed_by_identity_id` | String, FK → `profiles.identity.id` (SET NULL) | nullable |
| `claimed_at` | DateTime | nullable |
| `created_by_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `created_at` | DateTime | |

Unique index `uq_ilc_member_roster_group_number` on `(group_identity_id,
ilc_registration_number)` — uniqueness is scoped per group, not global.

---

## `meeting_room` schema (Task 3)

Reply configuration (role/tone/complexity/character/language) deliberately
lives in `profiles.permission`, not a table here — this room's Config
Board is a view over that data. Calendar and Archive Locker are likewise
reused from `core` (`room=RoomName.meeting_room`).

### `conversation`
A WhatsApp thread with one identity.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `status` | Enum `conversation_status` (`active`, `archived`) | default `active` |
| `target_language` | String(50) | default `"auto"` — `"auto"` mirrors whatever language the community member writes in |
| `tone` | String(50) | default `""` |
| `character_name` | String(100) | default `""` |
| `character_role` | String(200) | default `""` |
| `initiated_by_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `created_at` / `updated_at` | DateTime | |

Empty tone/character values fall back to the identity's effective reply
config from `profiles.permission`. Relationship: `conversation.messages` →
`message` (cascade delete-orphan, ordered by `created_at`).

### `message`
One WhatsApp message.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK, autoincrement | |
| `conversation_id` | String, FK → `meeting_room.conversation.id` (CASCADE) | not null, indexed |
| `direction` | Enum `message_direction` (`inbound`, `outbound`) | not null |
| `mode` | Enum `reply_mode` (`auto`, `manual`, `adaptive`) | nullable |
| `original_text` | Text | default `""` — what the sender actually wrote |
| `detected_language` | String(20) | default `""` |
| `translated_text` | Text | default `""` — the cross-language rendering |
| `final_text` | Text | not null — what actually went over WhatsApp |
| `tone_analysis` | JSONB | default `{}` — inbound only, tone-analysis agent output |
| `key_points` | JSONB (list) | default `[]` — outbound only, translation-agent topic tags |
| `sent_by_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `provider_message_id` | String(255) | default `""` |
| `created_at` | DateTime | indexed |

### `meeting`
A scheduled/live/completed video meeting.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `host_identity_id` | String, FK → `profiles.identity.id` (CASCADE) | nullable, indexed — null for `meeting_kind="staff"` (staff aren't identity-tree nodes) |
| `scheduled_at` | DateTime | not null |
| `meeting_kind` | String(20) | default `"community"` — `"staff"` \| `"client_org"` \| `"community"` |
| `translate_live` | Boolean | default true |
| `translate_languages` | JSONB (list of str) | default `["en"]` — per-meeting language whitelist the join UI offers, capped at `MAX_TRANSLATE_LANGUAGES` |
| `status` | Enum `meeting_status` (`scheduled`, `live`, `completed`, `cancelled`) | default `scheduled` |
| `notes` | Text | default `""` |
| `created_by` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_at` | DateTime | |
| `room_name` | String(80) | unique, not null — the LiveKit room, derived as `f"meeting-{id}"` |
| `started_at` / `ended_at` | DateTime | nullable |

Relationship: `meeting.participants` → `meeting_participant` (cascade
delete-orphan).

### `meeting_participant`
One row per person invited to a meeting.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `meeting_id` | String, FK → `meeting_room.meeting.id` (CASCADE) | not null, indexed |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | nullable |
| `staff_user_id` | String, FK → `core.staff_user.id` (CASCADE) | nullable |
| `guest_name` | String(200) | nullable — set only for open-invite-link joins, never deduplicated |
| `joined_at` / `left_at` | DateTime | nullable |
| `created_at` | DateTime | |

Check constraint `one_actor`: exactly one of `identity_id`,
`staff_user_id`, `guest_name` is set. Partial unique indexes:
`(meeting_id, identity_id)` where `identity_id IS NOT NULL`,
`(meeting_id, staff_user_id)` where `staff_user_id IS NOT NULL`.
Relationship: `meeting_participant.invite` → `meeting_invite`
(1:1, cascade delete-orphan).

### `meeting_invite`
A passwordless, time-bound join link.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `meeting_id` | String, FK → `meeting_room.meeting.id` (CASCADE) | not null, indexed |
| `kind` | Enum `meeting_invite_kind` (`personal`, `open`) | default `personal` — `personal` ties to one `meeting_participant` and always mints the same LiveKit identity; `open` is meeting-wide and mints a fresh guest participant + LiveKit identity on every redemption |
| `participant_id` | String, FK → `meeting_room.meeting_participant.id` (CASCADE) | nullable, unique — null for `kind=open` |
| `token` | String(64) | unique, indexed, default `secrets.token_urlsafe(24)` |
| `is_active` | Boolean | default true |
| `expires_at` | DateTime | not null |
| `revoked_at` / `used_at` | DateTime | nullable |
| `created_at` | DateTime | |

Partial unique index `uq_meeting_invite_open_per_meeting` on `meeting_id`
`WHERE kind = 'open'` — at most one open invite per meeting.

### `whatsapp_link`
Phone number ↔ identity mapping — a "group" is this list plus 1:1
conversations (the Cloud API has no native groups).

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `phone_number` | String(32) | unique, indexed |
| `identity_id` | String, FK → `profiles.identity.id` (CASCADE) | not null, indexed |
| `created_at` | DateTime | |

### `session_report`
A generated analysis of a conversation, stored so a report isn't
re-generated (re-spending an LLM call) on every view.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `conversation_id` | String, FK → `meeting_room.conversation.id` (CASCADE) | not null, indexed |
| `report_type` | Enum `report_type` (`session_summary`, `satisfaction_analysis`, `member_summary`) | not null |
| `content` | JSONB | default `{}` — the agent's JSON output |
| `message_count` | Integer | default 0 |
| `generated_by_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `generated_by_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `created_at` | DateTime | indexed |

### `meeting_chat_message`
One row per in-call chat message during a live meeting — persisted so
chat survives a refresh/reconnect.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `meeting_id` | String, FK → `meeting_room.meeting.id` (CASCADE) | not null, indexed |
| `message_id` | String(64) | not null — client-generated idempotency key |
| `sender_identity` | String(200) | not null — raw LiveKit identity string (`"identity:<id>"`, `"staff:<id>"`, `"guest:<uuid>"`), not an FK |
| `original_text` | Text | not null |
| `source_language` | String(20) | not null |
| `translations` | JSONB | default `{}` — accumulates lazily, only languages actually needed |
| `created_at` | DateTime | indexed |

Unique index `uq_meeting_chat_message_id` on `(meeting_id, message_id)`.

---

## `tasking` schema (Task 4)

Internal staff task-tracking and inbox — the "common interface" regular
(non-admin) staff use. Tagged `RoomName.initial_tasking` for audit/ledger
consistency with every other room, though no ledger/spend activity
currently flows through it.

### `task`
Assigned by an admin to a staff account. "Assigner must be tier=admin" is
a service-layer rule, not a DB constraint.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `title` | String(255) | not null |
| `description` | Text | default `""` |
| `assigned_by_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `assigned_to_staff_id` | String, FK → `core.staff_user.id` (CASCADE) | not null, indexed |
| `status` | Enum `task_status` (`open`, `in_progress`, `blocked`, `completed`, `cancelled`) | default `open` |
| `due_date` | Date | nullable |
| `created_at` / `updated_at` | DateTime | |

Relationship: `task.updates` → `task_update` (cascade delete-orphan,
ordered by `created_at`).

### `task_update`
Append-only progress log for a task — never edited or deleted, so "latest
update" is just the newest row.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `task_id` | String, FK → `tasking.task.id` (CASCADE) | not null, indexed |
| `author_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `note` | Text | not null |
| `progress_status` | Enum `task_status` | nullable |
| `is_concern` | Boolean | default false — flags this update for the admin's "open concerns" view |
| `created_at` | DateTime | indexed |

### `inbox_message`
One polymorphic inbox for staff↔admin, staff↔staff, and client↔admin
notices.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `sender_staff_id` | String, FK → `core.staff_user.id` (SET NULL) | nullable |
| `sender_client_id` | String, FK → `core.client_user.id` (SET NULL) | nullable |
| `recipient_staff_id` | String, FK → `core.staff_user.id` (CASCADE) | nullable |
| `recipient_client_id` | String, FK → `core.client_user.id` (CASCADE) | nullable |
| `subject` | String(255) | default `""` |
| `body` | Text | not null |
| `related_task_id` | String, FK → `tasking.task.id` (SET NULL) | nullable |
| `related_meeting_id` | String, FK → `meeting_room.meeting.id` (SET NULL) | nullable |
| `read_at` | DateTime | nullable |
| `created_at` | DateTime | indexed |

Check constraints: `one_sender` — exactly one of `sender_staff_id`/
`sender_client_id`; `one_recipient` — exactly one of
`recipient_staff_id`/`recipient_client_id`. Indexes:
`(recipient_staff_id, read_at)`, `(recipient_client_id, read_at)` for
unread-count queries.

---

## Postgres ENUM types

Every Python `str, enum.Enum` above is materialized as a native Postgres
`ENUM` type (via SQLAlchemy's `Enum(..., name=...)`), not a `CHECK`
constraint on a plain string column. Adding a new member to any of these
requires an Alembic migration that runs `ALTER TYPE ... ADD VALUE` (or,
more commonly in this codebase's migration history, drops and recreates
the type) — it cannot be done with a plain column change.

| Enum type | Schema it's defined in | Members |
|---|---|---|
| `room_name` | `core` | `accounts`, `profiles`, `meeting_room`, `initial_tasking`, `specialise`, `resources`, `assets`, `hold_data` |
| `actor_type` | `core` | `staff`, `client`, `client_staff`, `system` |
| `ledger_entry_type` | `core` | `funding`, `customer_transfer`, `agent_spend`, `gate_charge`, `adjustment` |
| `archive_shelf` | `core` | `operational_library`, `transfer`, `receiving` |
| `archive_item_status` | `core` | `draft`, `approved`, `received`, `reviewed`, `accepted`, `rejected`, `active` |
| `webhook_direction` | `core` | `inbound`, `outbound` |
| `staff_tier` | `core` | `admin`, `staff` |
| `client_registration_status` | `core` | `pending`, `approved`, `rejected` |
| `tool_slot` | `core` | `whatsapp_send`, `reply_generator`, `comms_agent`, `video_provider`, `meeting_stt`, `meeting_tts`, `meeting_translation` |
| `account_category` | `accounts` | `ai_platform`, `comms_platform`, `payment`, `hosting`, `domain`, `government`, `banking`, `tool`, `other` |
| `financial_record_category` | `accounts` | `subscription`, `salary`, `contractor`, `api_usage`, `hosting`, `other` |
| `api_health_status` | `accounts` | `healthy`, `degraded`, `down`, `unknown` |
| `identity_type` | `profiles` | `group`, `member` |
| `permission_scope` | `profiles` | `none`, `within_tree`, `any` |
| `consent_context` | `profiles` | `onboarding`, `record_time` |
| `conversation_status` | `meeting_room` | `active`, `archived` |
| `message_direction` | `meeting_room` | `inbound`, `outbound` |
| `reply_mode` | `meeting_room` | `auto`, `manual`, `adaptive` |
| `meeting_status` | `meeting_room` | `scheduled`, `live`, `completed`, `cancelled` |
| `meeting_invite_kind` | `meeting_room` | `personal`, `open` |
| `report_type` | `meeting_room` | `session_summary`, `satisfaction_analysis`, `member_summary` |
| `task_status` | `tasking` | `open`, `in_progress`, `blocked`, `completed`, `cancelled` |

---

## Cross-schema foreign-key traffic

Foreign keys freely cross schema boundaries — this is a single database,
so cross-schema FKs are ordinary Postgres constraints, not a special case.
The two hubs almost everything eventually points back to:

- **`profiles.identity`** — referenced from `core` (`client_user`,
  `client_staff_user`, `ledger_entry`, `llm_usage_record`), `profiles`
  itself (`permission`, `profile_account`, `consent_record`,
  `group_invite`, `member_profile`, `ilc_member_roster`), and
  `meeting_room` (`conversation`, `meeting.host_identity_id`,
  `meeting_participant`, `whatsapp_link`).
- **`core.staff_user`** — referenced from every schema as a "who did
  this" / "who does this belong to" column: `reviewed_by`, `created_by`,
  `assigned_to_staff_id`, `sent_by_staff_id`, etc.

Two important **non**-FK relationships to be aware of when reading the
models:

1. `core.refresh_token.client_user_id` / `client_staff_user_id` are plain
   indexed `String` columns, **not** foreign keys — they're read
   generically across three different login flows.
2. `meeting_room.meeting_chat_message.sender_identity` is a raw LiveKit
   identity string (`"identity:<id>"`, `"staff:<id>"`, `"guest:<uuid>"`),
   not a foreign key to any table — it's resolved to a display name at
   read time the same way the scheduler UI already resolves participants.

Two "XOR-actor" patterns recur across schemas, each enforced by a
`CheckConstraint` rather than a nullable-everything shrug:
`meeting_room.meeting_participant` (identity vs. staff vs. guest, exactly
one of three) and `tasking.inbox_message` (staff vs. client, independently
for sender and recipient).
