# Phase 1 — Core Schema & Auth ("PROMPT 2")

Scope: the new `orgs` schema (`Org`/`Group`/`OrgUser`/`Member`/
`OrgRegistrationRequest`/`GroupInvite`) and a parallel org-side auth
system, plus `core.agent_run_log` (table only). **Additive, not a
cutover** — `app/profiles/*`, `app/accounts/*`, `app/meeting_room/*`,
`app/tasking/*` are untouched (verified via `git status`: none of those
paths show changes introduced by this phase).

## Decisions made

- **Group modeling** (user-locked): a real `orgs.group` table — `Org →
  Group → Member`, max depth 3, no recursion — folding in the old
  `IlcGroupProfile`'s 13 fields directly, so no structured per-group data
  is lost.
- **Admin JWT audience** (user-locked): kept ONE `"staff"` audience.
  Admin-only routes stay gated by `require_admin`'s DB-reverified tier
  check (unchanged, already correct) rather than a separate `"admin"`
  audience.
- **`"org"` as a 4th JWT audience literal**, distinct from legacy
  `"client"`/`"client_staff"` — two independently-evolving auth systems
  never share one audience string with disjoint id-spaces as an unstated
  invariant. Zero risk, keeps `token_service.py`'s 1:1 audience→column
  mapping intact.
- **Real FK on `refresh_token.org_user_id`** (`orgs.org_user.id`,
  CASCADE) — unlike the two legacy `client_user_id`/`client_staff_user_id`
  columns (predate this, left as plain indexed strings, not touched).
- **`Member` deliberately minimal**: id, org_id, group_id (nullable),
  name, is_active, timestamps. Phone/email/registration fields are
  Prompt 3's job (member self-registration via `group_invite` redemption
  is explicitly that phase's item) — the table exists now so Prompt 3 is
  an additive column migration, not a new table.
- **`group_invite` gets both `org_id` (required) and `group_id`
  (nullable) up front** — null means "invite for direct org membership,"
  avoiding a Prompt-3 schema-shape migration.
- **`orgs.code_sequence` kept separate** from `profiles.group_code_sequence`
  — zero table-level coupling between the new and legacy schemas.
- **`org_user.email` is globally unique**, matching `StaffUser`/
  `ClientUser` precedent. Open question below.
- **`needs_rehash()` wired in** to both the staff login path
  (`app/auth/router.py`) and the new org login path — was dead code
  before this phase (defined, never called).
- **New `ActorType.org_user`** and **`RoomName.orgs`** enum values added
  (`core.models.audit`, `core.models.common`) so org-side audit entries
  are unambiguous about which table an actor/room refers to, rather than
  overloading the legacy `client`/`client_staff`/`profiles` values.

## What already existed vs. what's new

Staff auth (`/api/auth/staff/bootstrap|login|refresh|logout|me|staff`,
argon2id, login lockout, refresh rotation with reuse-detection) was
**already fully built and correct** before this phase — the only staff-
auth work was closing a real test-coverage gap (`test_staff_auth_e2e.py`:
no prior test exercised these routes end-to-end, only a dependency-level
probe-app pattern existed) and wiring `needs_rehash()`.

Net-new: `app/orgs/` package (`models.py`, `services.py`, `security.py`,
`router.py`, `schemas.py`), `app/core/models/agent_run_log.py`, migration
`c4d5e6f7a8b9_orgs_schema_and_agent_run_log.py`, five new test files.

## Explicit confirmation: legacy code untouched

`git status` after this phase shows changes only in: the new `app/orgs/`
package, `app/core/models/agent_run_log.py`, the new migration, and
mechanical auth-infra edits (`app/core/security/jwt.py`,
`app/core/security/cookies.py`, `app/core/services/token_service.py`,
`app/core/models/staff.py`, `app/core/models/common.py`,
`app/core/models/audit.py`, `app/core/models/__init__.py`,
`alembic/env.py`, `app/database.py`, `app/main.py`, `app/auth/router.py`).
`app/profiles/*`, `app/accounts/*`, `app/meeting_room/*`, `app/tasking/*`
show the same pre-existing modifications they had before this phase
(the in-flight Tools Registry work and an earlier Google-only
meeting-translation trim, both from prior sessions) — nothing in this
phase added to or touched those diffs. WhatsApp's orchestrator and the
Tools Registry keep reading `profiles.Permission.effective_*` exactly as
before; no FK was repointed.

## Open questions for Prompt 3/4

- **`Org.balance` vs. the old per-identity `ProfileAccount` fidelity**:
  the legacy system had one balance row per identity in the tree (org
  root, every group, every member). `Org.balance` here is a single
  denormalized running total — a known simplification, not solved in
  this phase. Whichever phase builds spend-gating against this schema
  needs to decide whether per-group/per-member balances come back.
- **`IlcMemberRoster`/`ConsentRecord` attachment**: how these eventually
  attach once `Member`/`GroupInvite` redemption is built in Prompt 3.
- **`tasking` schema's fate**: ADR-0003 named this phase as where it'd be
  resolved; punted again since none of Prompt 2's six directive items
  touch staff tasking.
- **`org_user.email` global uniqueness**: means one person can't be an
  `org_user` in two different orgs with the same email. Not needed by
  anything built so far — flagged, not blocking.

## Roadmap

Prompt 3 — WhatsApp service (member self-registration via `group_invite`,
`Conversation`/`Message`/`phone_link`, the inbound pipeline). Prompt 4 —
Meeting Room + plugin entitlements. Prompt 5 — Staff observability &
WhatsApp test console (this is where `agent_run_log` call sites actually
get wired). Prompt 6 — Frontend: three dashboards. Prompt 7 — Hardening
pass.

## Verification

- `pytest tests/ -v` — 113 passed (107 existing + 6 new).
- `alembic upgrade head` clean; `alembic downgrade -1` → `upgrade head`
  round-trips cleanly, confirmed against the live dev DB.
- Manual walk of the registration flow confirmed via the new
  `test_org_registration_flow.py` (public register → admin approve → org
  login, through the real routes, asserting an `audit_log` row after each
  mutation).
