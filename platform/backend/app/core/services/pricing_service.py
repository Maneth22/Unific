"""Client-facing billing markup — a presentation-layer transform, not a
second source of truth. Admin-facing reads (`app.accounts`,
`llm_usage_service`) always return the raw provider/service cost;
client-facing reads apply `apply_markup()` at the router boundary so both
views come from the exact same underlying rows, one priced at cost and
one priced at what the client is billed.
"""
from __future__ import annotations

from decimal import Decimal

# A single global markup rate for now (not per-client/per-service) — see
# platform's roles/profiles redesign plan. Applied uniformly to LLM token
# costs and every other billable service the same way.
CLIENT_MARKUP_RATE = Decimal("0.30")


def apply_markup(raw_cost: Decimal | None) -> Decimal | None:
    if raw_cost is None:
        return None
    return raw_cost * (Decimal("1") + CLIENT_MARKUP_RATE)
