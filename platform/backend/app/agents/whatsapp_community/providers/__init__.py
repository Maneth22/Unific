"""Gemini-backed (and mock/stub) implementations of the `CommsAgent` /
`ReplyGenerator` ABCs (`app.core.providers.base`), specific to the
WhatsApp community agent — moved here from `app.core.providers` so the
agent's own behavior lives with the agent, while the ABCs and transport-
level providers (WhatsApp send/receive, Gemini's low-level call wrapper)
stay in `core` for reuse by future agents.
"""
