# Legacy documentation (pre-rewrite reference only)

These three documents describe the pre-rewrite UNIFIC architecture — the
old five-schema scheme (`core` / `accounts` / `profiles` / `meeting_room` /
`tasking`), the eight-room model, the identity tree, and the Tools
Registry. They are kept here for **historical reference only** and are
**not** updated as the UNIFIC v2 rewrite proceeds.

For current architecture decisions, see [`../adr/`](../adr/). For rewrite
progress phase by phase, see [`../PHASE_0_NOTES.md`](../PHASE_0_NOTES.md)
(and later `PHASE_N_NOTES.md` files as they land).

| File | What it was |
|---|---|
| [`PLATFORM_README.md`](PLATFORM_README.md) | System-level map: the eight-room model, shared core infrastructure, external providers, local dev setup |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Detailed room-contract spec new rooms had to follow: audit pattern, provider ABC + mock pattern, Tools Registry |
| [`DATABASE_SCHEMA.md`](DATABASE_SCHEMA.md) | Full table-by-table schema reference for the old five-schema layout |

Decisions worth carrying forward into the rewrite (string-UUID PKs, the
`NAMING_CONVENTION` dict, the `actor_type`/`actor_id` audit helper, the
provider ABC + mock pattern, JWT-audience-per-login-type) are called out
explicitly in the ADRs and phase notes as they're reused — don't port code
from these files wholesale, they're context, not a spec to follow.
