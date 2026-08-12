"""Home for UNIFIC's own agents — code organized by *behavior*, not by
`RoomName` (see `app.core.models.common.RoomName`). The WhatsApp community
agent (`app.agents.whatsapp_community`) is the first; its transport-level
providers (WhatsApp send/receive, LiveKit, Gemini's low-level call wrapper)
stay in `app.core.providers` since those are reusable by any future agent
here, not owned by this one.
"""
