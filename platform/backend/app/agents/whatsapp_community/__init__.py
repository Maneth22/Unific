"""The WhatsApp community agent — chats with registered ILC community
members over WhatsApp on the Meeting Room's behalf. `orchestrator.py` is
the entry point (`receive_inbound_message`, called from
`app.meeting_room.router`'s webhook); `session_store.py` holds same-day
conversation state in Redis; `flush_service.py` + `scheduler.py` persist
it to Postgres at end of day; `providers/` holds the Gemini-backed (and
mock) implementations of the `CommsAgent`/`ReplyGenerator` ABCs from
`app.core.providers.base`.
"""
