# ADR-0003: Target Postgres schema layout

## Status

Proposed — documentation of intent only. No migration runs, no
`SCHEMAS` tuple edit, and no model file changes happen as part of this
ADR or Phase 0. The actual cutover is designed and executed in the "core
schema & auth" rebuild phase.

## Context

The live scheme today (`app/database.py`, `SCHEMAS = ("core", "accounts",
"profiles", "meeting_room", "tasking")`) matches the old eight-room model.
The rebuild directive's target is a five-name scheme: `core`, `orgs`,
`whatsapp`, `meetings`, `plugins`.

## Decision

Document the target mapping now so later phases have a single reference
point, without touching the database yet:

| Old schema | New schema | Notes |
|---|---|---|
| `core` | `core` | Shared infra (calendar/archive/audit/room-account ledger) — name unchanged, contents narrow over time as rooms get cut. |
| `accounts` + `profiles` | `orgs` | Client/organization identity + permission model consolidates into one schema, flattened per the directive (`Org` → `Member`, no arbitrary-depth identity tree). |
| *(new — was ad hoc under `accounts`)* | `whatsapp` | The WhatsApp community agent gets its own schema instead of living split across `accounts`/`meeting_room`. |
| `meeting_room` | `meetings` | Renamed, same responsibility. |
| *(new)* | `plugins` | Replaces the Tools Registry (`app/core/models/tools.py`, `tools_registry.py`, `tools_service.py`, `tools_router.py`, `tools_schemas.py`, and its two in-flight Alembic migrations) with a `plugin_catalog` / `org_entitlement` model — no cascading `own_*`/`effective_*` inheritance. |
| `tasking` | — | Cut per the directive's scope decision (Tasks 4–8 reserved rooms are out of scope); exact disposition of any salvageable pieces is deferred to the core-schema-&-auth phase. |

`database.py`'s `NAMING_CONVENTION` dict (string-UUID PKs except
high-volume append-only tables, `ix_`/`uq_`/`ck_`/`fk_`/`pk_` naming) is
carried forward unchanged — it already matches the directive's "keep"
list verbatim; no ADR needed for it specifically.

## Consequences

This table is intent, not execution. Until the core-schema-&-auth phase:

- The database keeps running on the old five-schema layout.
- The uncommitted Tools Registry work-in-progress in the working tree
  stays untouched — it isn't deleted until `plugins` exists to replace
  it, per the directive's "delete old code only as the equivalent new
  piece lands" rule.

## Open question

Whether `plugins` fully replaces the Tools Registry 1:1, or whether some
of it (e.g. `core.tool_global_selection`'s non-meeting-room slots:
`whatsapp_send`, `reply_generator`, `comms_agent`, `video_provider`)
survives in a simpler form as plain `core` config rather than becoming
full marketplace entitlements. Left unresolved — decide when the
plugins/entitlement model is actually designed.
