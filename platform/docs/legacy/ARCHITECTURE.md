# UNIFIC Platform — Architecture

This document is the room contract, written down. It exists so that Task 4
(Initial Tasking), Task 5 (Specialise), Task 6 (Resources), Task 7 (Assets),
and Task 8 (Hold Data) can be added later by following the same shape the
first three rooms already use — without changing anything that exists today.

Ground truth for what each room must eventually do is
`Documents and guidelines/unific_task_subjects.html` (the MODEL array) and its
companion docs. This file describes how the three built rooms are actually
wired, so a new room can be dropped in consistently.

## The eight rooms, three built

| Task | Room | Status |
|---|---|---|
| 1 | Accounts | Built |
| 2 | Profiles | Built |
| 3 | Meeting Room (renamed from Communications) | Built |
| 4 | Initial Tasking | Not built |
| 5 | Specialise | Not built |
| 6 | Resources | Not built |
| 7 | Assets | Not built |
| 8 | Hold Data | Not built |

`app/core/models/common.py::RoomName` already lists all eight — a new room
needs a new value there only if the enum doesn't already cover it (it does).

## The room contract

Every room shares four things, and none of them are duplicated per room —
they live once in `core` and every room's business logic calls into them:

1. **A Postgres schema of its own** for room-specific business data
   (`accounts`, `profiles`, `meeting_room`, and — when built —
   `initial_tasking`, `specialise`, `resources`, `assets`, `hold_data`).
   Every model in that schema sets `__table_args__ = {"schema": "<room>"}`.
   Register new model modules in `alembic/env.py`'s import loop (already
   pattern-matched for `app.<room>.models`) and mount the router in
   `app/main.py`.

2. **A view onto the one master calendar** — `app.core.services.calendar_service`.
   A room submits its own timing (`submit_timing(room=RoomName.x, kind=...,
   due_at=...)`) rather than keeping a private calendar. Reads/writes are
   free — no model call, no external call.

3. **An Archive Locker** — `app.core.services.archive_service`, operating
   on `core.archive_item` rows tagged by `room`. Three shelves:
   Operational Library (the room's live working truth, `shelf=
   operational_library`), Transfer (outgoing, staged), Receiving (incoming,
   pending review). A room's "locker" is not a separate table — it is
   simply the set of `ArchiveItem` rows where `room = <that room>`. Nothing
   is ever auto-accepted: `propose_transfer` → `deliver` → `review` →
   `accept`/`reject` are four distinct, audited steps.

4. **A room account with one sub-account per agent** —
   `app.core.services.spend_service`. `ensure_room_account(room)` /
   `ensure_agent_sub_account(room, agent_name)` create the rows on first
   use; `record_spend(room, agent_name, amount, description)` debits both
   and writes one `core.ledger_entry` row. This is how UNIFIC's own
   operating cost stays traceable to the agent that incurred it — see
   `scripts/seed_rooms.py`, which seeds every room's account and its
   agents' sub-accounts up front so the first real spend call doesn't hit
   a missing row.

A fifth piece exists but is cross-room by design, not per-room: **the
gate**, `app.core.services.gate_service.check_and_charge()`. Everything up
to and including a Meeting Room reply drawn from the room's own Shelf 1 is
UNIFIC's free-to-near-free running cost (tracked via `spend_service`
against the room's own account, *not* the member's). Going past that —
which Tasks 4-8 will do — means calling `check_and_charge(identity_id,
room, action, cost>0)` first: it reads `profiles.permission.effective_*`
and `profiles.profile_account.balance`, raises if the identity isn't
registered or can't afford it, otherwise debits the identity's own balance
and writes a `gate_charge` ledger entry. **No future room should ever
spend an identity's credit without going through this function.**

## The identity tree (Task 2) that everything else reads

`profiles.identity` is a self-referencing tree (Group → Group → … →
Member, arbitrary depth). Ancestor/descendant scope checks use a
materialized `path` column (dot-joined ancestor ids) with a
`text_pattern_ops` index — see `app.core.services.scope_service`. This is
a deliberate substitution for the `ltree` extension the original design
called for: `ltree`'s wire format needs a custom asyncpg codec to read
back, which was judged not worth the operational risk at pilot scale. The
extension is still enabled in the database (first migration) if a future
maintainer wants to switch.

Permissions narrow going down the tree and are precomputed, not merged
live: `profiles.permission.effective_*` is recomputed by
`app.profiles.services.recompute_cascade()` (parent-first, via
`scope_service.descendant_ids`) any time `own_*` changes or a subtree
moves. The narrowing rule is enforced by construction, not by rejecting
wide values — booleans use AND with the parent's effective value, ranked
scopes use MIN, credit caps use MIN — so even a bad write can't produce an
effective value wider than the parent allows. A future room reading
permissions should always read `effective_*`, never attempt to walk
ancestors itself.

## Client onboarding & community registration (Task 2, client-facing)

Four flows sit on top of the identity tree, all added after the initial
three-room build. None of this touches messaging/group-chat mechanics —
"community" here is purely a `profiles.identity` grouping concept. Each
member created by these flows still gets the same individual 1:1
`meeting_room.Conversation` every identity has always gotten; there is no
group-chat construct anywhere in this section (see "What's paused" below).

1. **Client self-registration + Admin approval.** A prospective client
   (e.g. LandChange) submits `POST /api/profiles/public/client-signup`
   (unauthenticated — org name, contact name, email, password) which
   stages a `core.client_registration_request` row (`status=pending`).
   `ClientUser.identity_id` is `NOT NULL` and read as non-optional
   everywhere (`require_identity_scope`, every client route), so a
   signup can't become a real login until it has an identity — hence the
   staging table rather than a half-formed `ClientUser`. An Admin reviews
   the queue (`GET/POST /api/profiles/registration-requests`); approving
   one (`app.profiles.services.approve_client_registration`) atomically
   creates a new root Group `Identity` (named after `org_name`) via the
   same `create_identity` every other identity goes through, then creates
   the real `ClientUser` bound to it and activates the login — one step,
   not two separate admin actions.

2. **Client-created community groups.** Once logged in, a client creates
   child Group identities under their own subtree —
   `POST /api/profiles/client/communities` — scope-checked the same way
   every other client-facing identity write is
   (`require_identity_scope`/`scope_service.is_ancestor_or_self`).
   `create_identity` itself no longer hardcodes `staff_id`; like
   `update_own_permission`/`fund_identity`/`transfer_credit` before it, it
   now takes the generic `actor_type`/`actor_id` keyword pair, so both
   staff and client (and the public flow below, as `ActorType.system`)
   share one creation path. **A newly created client group is opened for
   auto-reply on creation** (`own_connected=True`, `own_auto_respond=True`
   set immediately after creation) — every other new identity inherits
   `connected=False` by default (closed until someone opens it), but that
   default would silently leave every member who self-registers under a
   brand-new community unable to get a reply until a human manually
   flipped those two flags, which defeats the entire point of flow 3
   below. This is a deliberate, narrow exception to the closed-by-default
   posture, made only for client-created groups, not a general relaxation.

3. **Group registration invites.** `profiles.group_invite` is a public,
   revocable link (`secrets.token_urlsafe`) targeting one Group identity;
   at most one row may be `is_active` per group (DB-enforced via a
   partial unique index) — regenerating deactivates the current row and
   inserts a new one rather than mutating the token in place, so a leaked
   old link goes cold and the full history of tokens issued survives.
   Created automatically alongside a new community group, and
   regenerable via `POST .../communities/{id}/invite/regenerate`.

4. **Public community-member registration.** A member visits
   `/register/<token>` (frontend) → `GET /api/profiles/public/invite/{token}`
   (backend, unauthenticated) to see which group/org they're joining, then
   `POST /api/profiles/public/invite/{token}/register` (name, email,
   mobile, free-form `extra_info`) creates, in one transaction: a Member
   `Identity` under the invite's group (`actor_type=system`), a
   `profiles.member_profile` row (the descriptive record — deliberately
   duplicates `phone_number` with `meeting_room.WhatsAppLink`, which stays
   the operational routing record the message pipeline actually reads,
   same "no cross-schema back-reference" style used elsewhere), the
   `WhatsAppLink` itself (via `meeting_room.services.link_phone_number`,
   called directly from the `profiles` router — routers cross room
   boundaries, services don't, matching the existing convention), and a
   `ConsentRecord` (`context=onboarding`, self-submitted). This
   orchestration lives in `app/profiles/router.py`, not
   `profiles/services.py`, specifically to avoid introducing a
   `profiles → meeting_room` service-layer dependency that doesn't exist
   today (today only `meeting_room → profiles` does). Registration is
   **instant, no review** — the response is a `wa.me` click-to-chat deep
   link (`settings.whatsapp_agent_display_number` +
   `settings.whatsapp_invite_prefill_template`) the frontend hard-redirects
   the browser to immediately.

**What's paused**: a client selecting multiple members from a community
and starting one shared "meeting room" WhatsApp group session (real-time
fan-out translation, group transcript) is explicitly *not* built by any of
the above — the WhatsApp Cloud API has no native group-messaging support,
and the simulated-fan-out alternative needs a decision before it's built.
`meeting_room.Meeting` remains the same disconnected calendar stub it was
before this section existed.

## Security boundaries that must hold for any new room

- **Staff (master dashboard):** every staff account is a full Admin —
  there is no per-room grant model any more (the previous
  `require_room_access(RoomName.<room>, RoomPermission.<read|write|admin>)`
  / `core.staff_room_access` grant table were removed by deliberate
  choice). Gate every staff route with `require_admin` from
  `app.core.security.dependencies` — any active staff account passes,
  checked server-side on every request, never assume the frontend hid a
  nav item. One consequence worth calling out explicitly: the Accounts
  room's `reveal_secret` (see Secrets below) used to require the
  stricter `RoomPermission.admin` tier specifically; it now only requires
  "is an active staff member," same as every other staff route.
- **Client (group-ID dashboard):** gate with
  `app.profiles.security.require_identity_scope()`, which checks the
  target identity is the client's own root or a descendant of it via
  `scope_service.is_ancestor_or_self`. See `tests/test_identity_scope.py`
  for the exact test this must keep passing: a valid client login must be
  blocked from an ancestor or an unrelated sibling tree.
- **Every mutating route writes an audit row** via
  `app.core.services.audit_service.record()`, with the real actor
  (`ActorType.staff` / `.client` / `.system`) and their id — never hardcode
  `ActorType.staff` in a service function that a client route also calls
  (this was a real bug caught and fixed during Task 2's build; see the
  `actor_type`/`actor_id` keyword-only parameters on
  `app.profiles.services.update_own_permission` / `fund_identity` /
  `transfer_credit` / `create_identity` as the pattern to copy).
- **Secrets** (`accounts.account_registry_entry.secret_ciphertext`) are
  Fernet-encrypted and only ever decrypted through
  `app.accounts.services.reveal_secret`, which requires an active staff
  (Admin) account — there is no stricter room-level tier above that any
  more, see the staff bullet above — and always audit-logs, success or
  failure. No future room should read a raw secret value directly, and no
  secret should ever be assembled into a payload sent to a provider/LLM
  call.

## Provider interfaces (Tasks 6-7 will need the same shape)

`app.core.providers.base` defines `WhatsAppProvider`, `TranslationProvider`,
`ReplyGenerator` as ABCs, deliberately in `core` rather than `meeting_room`,
because Resources (external data gathering) and Assets (building things
from held data) will need identically-shaped external connectors — a
provider ABC, a mock implementation for development, and a real
implementation gated behind env config. `app.core.providers.factory`
is the one place that reads which implementation is selected; nothing else
should import a concrete provider class directly. `MockWhatsAppProvider`
deliberately simulates occasional failures (`ProviderError`) so a room's
error handling is proven before real credentials exist — do the same for
any new provider.

**Status**: `ReplyGenerator` and `TranslationProvider` are real as of
`REPLY_PROVIDER=gemini` / `TRANSLATION_PROVIDER=gemini` (the default) —
see `gemini_reply_generator.py` / `gemini_translation_provider.py`, both
built on the shared rate-limited wrapper in `gemini_client.py`. The reply
generator is prompt-constrained to only use the `context_snippets` it's
given (Shelf 1, `approved_for_auto_reply=True`) and returns the
deterministic fallback rather than guessing when nothing relevant is
found. `WhatsAppProvider` is still mock-only — `WHATSAPP_PROVIDER=cloud_api`
exists as a stub (`cloud_api_whatsapp.py`) but hasn't been exercised
against the real Cloud API yet. Every provider call in the message
pipeline (`meeting_room/services.py`) is wrapped so a `ProviderError` —
including "Gemini is not configured" when `GEMINI_API_KEY` is unset —
degrades to a safe fallback (the stub reply, or untranslated text) rather
than crashing the pipeline; see the try/except blocks in
`receive_inbound_message` / `_auto_reply` / `send_manual_reply`.

## The comms room agent (the Meeting Room's intermediary layer)

`CommsAgent` (`core/providers/base.py`) is the port of the prototype's
four comms-room agents (E:\Unific-Solutions\backend\prompts), plus a new
satisfaction analysis — one provider, five actions, selected via
`COMMS_AGENT_PROVIDER=gemini|mock`:

- `clarify_inbound` — community WhatsApp message → detected language +
  clear-English restatement (stored on `message.translated_text`; the
  client's chat shows this, with the raw original underneath).
- `analyze_tone` — per inbound message: proficiency / emotional tone /
  politeness / style + one-line insight (stored on `message.tone_analysis`).
- `translate_outbound` — client English → the room's configured language,
  tone, and **character voice** ("Jake, a student volunteer"), using the
  recent chat history so `target_language="auto"` mirrors whatever
  language the community member writes in. Returns key-point tags
  (stored on `message.key_points`). Facts must survive translation — the
  prompt forbids dropping amounts/dates/promises.
- `generate_session_report` / `generate_satisfaction_analysis` — full
  transcript (raw + clarifications + tone insights) → stored
  `meeting_room.session_report` rows the client can revisit for free.
- `generate_member_summary` — same transcript input as the two above, but
  framed as an ongoing community-member profile rather than a single
  session's recap; surfaced on the client dashboard's Profiles tab
  (community roster) via `report_type=member_summary` on the same
  generic report endpoints. `generate_report`'s dispatch
  (`meeting_room/services.py`) is an explicit three-way branch on
  `ReportType`, not an `if/else` — a two-way `if session_summary: ... else:
  satisfaction`, which is what it was before this action existed, would
  have silently routed `member_summary` into the satisfaction-analysis
  agent instead of raising or doing the right thing.

Room configuration lives on `meeting_room.conversation`
(`target_language`/`tone`/`character_name`/`character_role`), set by
whoever initiates the room (`POST .../conversations/initiate`, staff or
scope-checked client); unset values fall back to the identity's inherited
reply config from `profiles.permission` (see `_room_config` in
`meeting_room/services.py`). Prompts live in
`core/providers/comms_prompts.py` — they were tuned on real community
conversations in the prototype; edit with care.

The shared Gemini client retries transient 503/429 errors with backoff
(`gemini_client._TRANSIENT_MARKERS`) — free-tier flash-lite throws
regular capacity 503s — and every degraded fallback in the pipeline logs
a warning instead of failing silently.

## AI usage tracking (recording only — no limits enforced yet)

Every real LLM call (Gemini reply drafting, translation, language
detection) writes one row to `core.llm_usage_record` — see
`app.core.services.llm_usage_service.record_usage()`, called from inside
`GeminiReplyGenerator` / `GeminiTranslationProvider` after each successful
call, never from the mock/stub providers. Each row carries `identity_id`,
`room`, `agent_name`, `provider`, `model`, `action`
(`reply_generation`/`translation`/`language_detection`), token counts
from the provider's own `usage_metadata`, and an estimated cost computed
from `settings.gemini_*_cost_per_1k_tokens` (an estimate — correct it
against real billing, see the setting's docstring in `config.py`).

Two read paths exist today: `GET /api/accounts/ai-usage/summary` (staff,
per-identity totals across the system — the Accounts Room's "AI Usage"
tab) and `GET /api/profiles/identities/{id}/ai-usage` (staff, one
identity's own history — the Profiles Room's "AI Usage" tab on a selected
identity).

**This is recording only.** No cap is enforced. The intended future hook:
add an `effective_token_limit_per_period` field to `profiles.permission`
(same narrowing-cascade pattern as `effective_credit_cap`), and have
`core.gate_service.check_and_charge` — or a new `check_llm_usage_allowed`
alongside it — sum `llm_usage_record.total_tokens` for the identity within
the current period before a provider call is allowed to proceed. Wire
that check into `meeting_room/services.py` right before the
`reply_generator.generate_reply()` / `translation_provider.translate()`
calls, mirroring how `gate_service.check_and_charge` already gates
`receive_inbound_message`.

## What Task 8 (Hold Data) will absorb

`core.ledger_entry` is currently the one append-only financial ledger for
the whole system — it stands in for Task 8 until that room is built. When
Hold Data is built, the natural migration is: Hold Data becomes the
permanent home for the ledger (and for `core.audit_log`'s room-scoped
history), while `core.ledger_entry` keeps its current role as the live
write path every room's spend/gate calls hit. Do not build a second,
competing ledger in Task 8 — extend this one.

## Local development

See `README.md` for setup. In short: `docker compose up -d` for Postgres,
`alembic upgrade head`, `python -m scripts.seed_rooms`, `uvicorn app.main:app`,
`npm run dev` in `frontend/`.
