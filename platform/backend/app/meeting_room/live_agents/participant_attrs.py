"""Participant attribute names + the live per-meeting registry of
everyone's current settings. Attributes are plain LiveKit participant
attributes (`localParticipant.setAttributes({...})` on the frontend) —
there's no DB schema for any of this, they only ever live on the LiveKit
room's own participant state.

Four distinct attributes, four distinct meanings — this is the deliberate
fix for the old system's single overloaded `language` attribute, which
conflated "what I speak" with "what I want to hear":

- `spoken_language`  — what this participant speaks (drives their own STT).
- `caption_language`  — what they want captions/dubbed-audio in.
- `audio_mode`        — "captions_only" | "dubbed_audio".
- `chat_language`     — what they want to READ chat in; defaults to
  `caption_language` if unset (see `ParticipantSettings.from_participant`).
"""
from __future__ import annotations

from dataclasses import dataclass

from livekit import rtc

ATTR_SPOKEN_LANGUAGE = "spoken_language"
ATTR_CAPTION_LANGUAGE = "caption_language"
ATTR_AUDIO_MODE = "audio_mode"
ATTR_CHAT_LANGUAGE = "chat_language"

AUDIO_MODE_CAPTIONS_ONLY = "captions_only"
AUDIO_MODE_DUBBED_AUDIO = "dubbed_audio"


@dataclass(frozen=True)
class ParticipantSettings:
    identity: str
    spoken_language: str
    caption_language: str
    audio_mode: str
    chat_language: str  # already resolved via the defaults-to-caption_language rule

    @classmethod
    def from_participant(cls, participant: rtc.Participant, *, default_language: str) -> "ParticipantSettings":
        attrs = participant.attributes or {}
        spoken = attrs.get(ATTR_SPOKEN_LANGUAGE) or default_language
        caption = attrs.get(ATTR_CAPTION_LANGUAGE) or default_language
        audio_mode = attrs.get(ATTR_AUDIO_MODE) or AUDIO_MODE_CAPTIONS_ONLY
        # The one default rule the spec calls out explicitly: chat_language
        # defaults to caption_language, not to default_language directly —
        # so a participant who only ever set caption_language still gets a
        # sensible chat_language without the frontend having to broadcast
        # a fourth attribute unless they actually diverge it.
        chat = attrs.get(ATTR_CHAT_LANGUAGE) or caption
        return cls(
            identity=participant.identity,
            spoken_language=spoken,
            caption_language=caption,
            audio_mode=audio_mode,
            chat_language=chat,
        )


class ParticipantRegistry:
    """The room's live participant-settings cache, and the exact
    dedup-by-distinct-target-language grouping both captions.py and
    chat_relay.py rely on. Kept up to date by the orchestrator's room
    event handlers (`update()`/`remove()`), never by re-reading every
    participant's attributes fresh on every segment/message — that keeps
    a caption/chat dispatch a pure in-memory dict operation, not a
    dict-scan-then-attribute-read per recipient."""

    def __init__(self, *, default_language: str):
        self._default_language = default_language
        self._settings: dict[str, ParticipantSettings] = {}

    def update(self, participant: rtc.Participant) -> ParticipantSettings:
        settings_ = ParticipantSettings.from_participant(participant, default_language=self._default_language)
        self._settings[participant.identity] = settings_
        return settings_

    def remove(self, identity: str) -> None:
        self._settings.pop(identity, None)

    def get(self, identity: str) -> ParticipantSettings | None:
        return self._settings.get(identity)

    def all(self) -> list[ParticipantSettings]:
        return list(self._settings.values())

    def distinct_caption_languages(self, *, exclude_identity: str) -> dict[str, list[str]]:
        """`{target_lang: [identity, ...]}` — one entry per distinct
        `caption_language` currently in use among everyone except
        `exclude_identity` (a speaker never gets a caption of their own
        speech). A listener whose `caption_language` matches the segment's
        `source_lang` is still included here — captions.py's caller skips
        the Gemini call for that language but still sends the original
        text to those recipients, so they're still a "needed" group, just
        one that doesn't need translation."""
        grouped: dict[str, list[str]] = {}
        for s in self._settings.values():
            if s.identity == exclude_identity:
                continue
            grouped.setdefault(s.caption_language, []).append(s.identity)
        return grouped

    def distinct_dubbed_languages(self) -> set[str]:
        """Every `caption_language` currently requested by at least one
        participant in `audio_mode=dubbed_audio` — the exact set
        `DubbedAudioManager.sync()` diffs against active pipelines."""
        return {s.caption_language for s in self._settings.values() if s.audio_mode == AUDIO_MODE_DUBBED_AUDIO}

    def chat_recipients_by_language(self, *, source_lang: str, exclude_identity: str) -> dict[str, list[str]]:
        """Same shape/semantics as `distinct_caption_languages`, keyed by
        `chat_language` instead — used by chat_relay.py identically."""
        grouped: dict[str, list[str]] = {}
        for s in self._settings.values():
            if s.identity == exclude_identity:
                continue
            grouped.setdefault(s.chat_language, []).append(s.identity)
        return grouped
