"""Phone-number normalization shared by `meeting_room/services.py` (writing
a WhatsAppLink) and `app.agents.whatsapp_community.orchestrator` (reading
one on every inbound webhook message) — both sides of the same lookup have
to agree on one representation, so this lives in its own tiny module
instead of being duplicated or privately owned by either.
"""
from __future__ import annotations


def normalize_phone(phone: str) -> str:
    """WhatsApp Cloud API's inbound webhook `from` field is always plain
    digits — country code + number, never a leading "+" or any spacing/
    punctuation. A number typed or pasted into a form (registration, a
    client adding a member) very commonly includes a "+" though, and
    comparing those two representations as exact strings silently fails
    forever — every WhatsAppLink write and lookup goes through this
    first so both sides agree on one representation."""
    return "".join(ch for ch in phone if ch.isdigit())
