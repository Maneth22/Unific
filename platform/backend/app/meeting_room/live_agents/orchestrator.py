"""Per-meeting orchestration — ties `ParticipantRegistry`,
`TranslatorManager`, `CaptionDispatcher`, `DubbedAudioManager`, and
`ChatRelay` together on one shared `rtc.Room` connection, and the
module-level `start_for_meeting`/`stop_for_meeting` entry points
`services.py` calls on meeting go-live / end (same call shape the old
`live_translation.py` exposed).

**One bot identity per meeting**, not one per language — a real departure
from the old per-language-bot design. It's no longer needed: STT is now
keyed by *speaker* (their `spoken_language`), translation is a stateless
Gemini call keyed by *(source, target)*, and dubbed-audio tracks are
distinguished by *track name* (`translated-<lang>`), not participant
identity. Nothing here requires a separate room connection per language
anymore, which is a real resource win on the 1vCPU/2GB droplet (one room
connection per meeting instead of up to `MAX_TRANSLATE_LANGUAGES`).

Runs embedded in this same FastAPI process (no separate LiveKit Agents
worker, and — see captions.py's own module docstring — no
livekit-agents `AgentSession` at all anymore either); this module mints
its own bot token and calls `room.connect()` itself, exactly like the
old `TranslationAgent.run()` did, keeping the "single bare uvicorn
process on a 1vCPU/2GB droplet" deployment unchanged.

In-memory `_running` registry: a backend restart mid-meeting drops
tracking of any still-running agent along with it — the same accepted
limitation the old `live_translation.py` documented (a fresh join after a
restart against a meeting still marked "live" will not get a new agent
started, since `services._mark_joined` only starts one on the
`scheduled` -> `live` transition). Not fixed here.
"""
from __future__ import annotations

import asyncio
import logging

from livekit import api as lk_api
from livekit import rtc

from app.config import settings
from app.core.services.tools_service import EffectiveToolConfig
from app.meeting_room.live_agents.captions import CaptionDispatcher
from app.meeting_room.live_agents.chat_relay import ChatRelay
from app.meeting_room.live_agents.dubbed_audio import DubbedAudioManager
from app.meeting_room.live_agents.participant_attrs import (
    ATTR_AUDIO_MODE,
    ATTR_CAPTION_LANGUAGE,
    ATTR_SPOKEN_LANGUAGE,
    ParticipantRegistry,
)
from app.meeting_room.live_agents import status
from app.meeting_room.live_agents.status import TranslationErrorScope
from app.meeting_room.live_agents.translation_backends import get_backend
from app.meeting_room.live_agents.translator import TranslatorManager

logger = logging.getLogger("live_agents.orchestrator")

# Bounds each of the three independent cost units server-wide, across
# every concurrently-running meeting on this process — see config.py's
# comments for exactly what each one guards. Deliberately separate from
# gemini_max_concurrent (the unrelated WhatsApp reply/translation path).
_stt_semaphore = asyncio.Semaphore(settings.live_agents_max_concurrent_stt_sessions)
_dubbing_semaphore = asyncio.Semaphore(settings.live_agents_max_concurrent_dubbing_pipelines)
_translate_semaphore = asyncio.Semaphore(settings.live_agents_max_concurrent_translate_calls)


class MeetingLiveAgent:
    """One per meeting."""

    def __init__(self, *, room_name: str, meeting_id: str, tool_config: EffectiveToolConfig):
        self._room_name = room_name
        self._meeting_id = meeting_id
        self._room = rtc.Room()
        self._registry = ParticipantRegistry(default_language=settings.live_agents_default_language)

        # tool_config is the meeting's resolved Tools Registry choice
        # (services._mark_joined resolves it once, at the scheduled->live
        # transition — see that function's docstring) — which backend/
        # provider each of the three pluggable pieces below actually uses.
        backend = get_backend(tool_config.meeting_translation)
        self._translator = TranslatorManager(backend=backend, semaphore=_translate_semaphore)
        self._captions = CaptionDispatcher(
            room=self._room,
            registry=self._registry,
            translator=self._translator,
            stt_semaphore=_stt_semaphore,
            stt_map=tool_config.meeting_stt,
            on_error=self._on_translation_error,
            on_recovered=self._on_translation_recovered,
        )
        self._dubbed = DubbedAudioManager(
            room=self._room, registry=self._registry, translate_semaphore=_dubbing_semaphore,
            on_error=self._on_translation_error, on_recovered=self._on_translation_recovered,
        )
        self._chat = ChatRelay(room=self._room, meeting_id=meeting_id, registry=self._registry, translator=self._translator)

        self._stopped = asyncio.Event()
        self._shutting_down = False

        self._room.on("participant_connected", self._on_participant_connected)
        self._room.on("participant_disconnected", self._on_participant_disconnected)
        self._room.on("track_subscribed", self._on_track_subscribed)
        self._room.on("track_unsubscribed", self._on_track_unsubscribed)
        self._room.on("participant_attributes_changed", self._on_participant_attributes_changed)
        self._room.on("active_speakers_changed", self._on_active_speakers_changed)
        self._room.on("disconnected", self._on_disconnected)

    async def run(self) -> None:
        token = (
            lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(settings.live_agents_bot_identity)
            .with_name("Translator")
            .with_grants(
                lk_api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
        ).to_jwt()
        logger.info(
            "live agent token minted identity=%s room=%s", settings.live_agents_bot_identity, self._room_name
        )

        await self._room.connect(settings.livekit_url, token, rtc.RoomOptions(auto_subscribe=True))
        logger.info("live agent connected room=%s identity=%s", self._room_name, settings.live_agents_bot_identity)
        self._chat.start()

        # auto_subscribe only covers tracks published *after* this point —
        # participants/tracks that already existed when we joined arrive
        # via the initial join response, not the live signaling path
        # auto-subscribe hooks into, so track_subscribed never fires for
        # them without an explicit subscribe + registry seed here (same
        # reasoning the old TranslationAgent.run() documented).
        #
        # registry.update() always runs, captions_enabled or not — chat
        # translation reads chat_language off the SAME registry and must
        # keep working regardless of whether captions/dubbing are on.
        for participant in self._room.remote_participants.values():
            if participant.identity == settings.live_agents_bot_identity:
                continue
            self._registry.update(participant)
            if not settings.live_agents_captions_enabled:
                continue
            for publication in participant.track_publications.values():
                if publication.kind != rtc.TrackKind.KIND_AUDIO or publication.source != rtc.TrackSource.SOURCE_MICROPHONE:
                    continue
                if not publication.subscribed:
                    publication.set_subscribed(True)
                self._captions.add_speaker(participant, publication)
        if settings.live_agents_captions_enabled:
            self._dubbed.sync()

        await self._stopped.wait()

        self._shutting_down = True
        await self._captions.stop_all()
        await self._dubbed.stop_all()
        await self._chat.stop()
        await self._room.disconnect()
        logger.info("live agent disconnected room=%s", self._room_name)

    def request_stop(self) -> None:
        self._stopped.set()

    def _on_translation_error(self, scope: TranslationErrorScope, subject: str, detail: str) -> None:
        """Fire-and-forget, mirrors every other callback in this class
        (e.g. `_on_active_speakers_changed`) — captions.py/dubbed_audio.py
        call this synchronously from inside their own except blocks, so
        it must never block or raise back into them. Only ever called
        after a caller's own report threshold is crossed (see
        dubbed_audio.LanguageAudioPipeline._supervise) — a single
        transient blip never reaches here at all."""
        asyncio.create_task(self._report_translation_error(scope, subject, detail))

    async def _report_translation_error(self, scope: TranslationErrorScope, subject: str, detail: str) -> None:
        # Deliberately does NOT touch translation_active — a per-speaker
        # or per-language degrade leaves the meeting-level flag True;
        # only a full agent crash (_log_agent_task_result below) flips it.
        await status.set_translation_error(self._meeting_id, detail)
        await status.broadcast_translation_status(self._room, scope=scope, subject=subject, detail=detail)

    def _on_translation_recovered(self, scope: TranslationErrorScope, subject: str) -> None:
        """Companion to `_on_translation_error` — fired once a session
        that had actually crossed the report threshold self-heals (see
        LanguageAudioPipeline._supervise), so a degraded bubble shown
        earlier clears on its own instead of waiting for a manual
        dismiss/retry."""
        asyncio.create_task(self._report_translation_recovered(scope, subject))

    async def _report_translation_recovered(self, scope: TranslationErrorScope, subject: str) -> None:
        await status.set_translation_error(self._meeting_id, None)
        await status.broadcast_translation_recovered(self._room, scope=scope, subject=subject)

    def _on_active_speakers_changed(self, speakers: list[rtc.Participant]) -> None:
        if not settings.live_agents_captions_enabled:
            return
        self._dubbed.on_active_speakers_changed(speakers)

    def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity == settings.live_agents_bot_identity:
            return
        self._registry.update(participant)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        self._registry.remove(participant.identity)
        if not settings.live_agents_captions_enabled:
            return
        self._captions.remove_speaker(participant.identity)
        self._dubbed.sync()

    def _on_track_subscribed(
        self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        if participant.identity == settings.live_agents_bot_identity:
            return  # never caption/dub the bot's own published (dubbed) tracks
        if track.kind != rtc.TrackKind.KIND_AUDIO or publication.source != rtc.TrackSource.SOURCE_MICROPHONE:
            return
        self._registry.update(participant)
        if not settings.live_agents_captions_enabled:
            return
        self._captions.add_speaker(participant, publication)
        self._dubbed.sync()

    def _on_track_unsubscribed(
        self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        if not settings.live_agents_captions_enabled:
            return
        self._captions.remove_speaker(participant.identity)

    def _on_participant_attributes_changed(self, changed_attributes: dict, participant: rtc.Participant) -> None:
        if participant.identity == settings.live_agents_bot_identity:
            return
        # Always applied — chat_language (read by chat_relay.py off this
        # same registry) must keep updating live regardless of whether
        # captions/dubbing are enabled.
        self._registry.update(participant)
        if not settings.live_agents_captions_enabled:
            return
        if ATTR_SPOKEN_LANGUAGE in changed_attributes:
            self._captions.on_spoken_language_changed(participant)
        if ATTR_CAPTION_LANGUAGE in changed_attributes or ATTR_AUDIO_MODE in changed_attributes:
            self._dubbed.sync()

    def _on_disconnected(self, reason) -> None:
        if self._shutting_down:
            logger.info("live agent room disconnected (shutdown) reason=%s", reason)
        else:
            logger.warning("live agent room disconnected unexpectedly reason=%s", reason)
        self._stopped.set()


_running: dict[str, tuple[MeetingLiveAgent, asyncio.Task]] = {}


async def start_for_meeting(
    room_name: str, meeting_id: str, languages: list[str], tool_config: EffectiveToolConfig
) -> None:
    """`languages` (the meeting's own `translate_languages`) is accepted
    for call-shape parity with the old module and stays a meaningful
    per-meeting scheduling-time UX whitelist (see schemas.py), but isn't
    otherwise consulted here — every participant's own
    `spoken_language`/`caption_language`/`audio_mode` attributes, not a
    pre-declared language list, reactively drive which STT/TTS/translate
    pipelines actually start (see `MeetingLiveAgent.
    _on_participant_attributes_changed`). `tool_config` is this meeting's
    resolved Tools Registry choice (see `meeting_room.services._mark_joined`,
    the only caller) — captured once, here, at meeting start; a later
    config change never affects this already-running agent (see
    docs/ARCHITECTURE.md's Tools Registry section on effect timing).
    Idempotent — a second call for a `meeting_id` already running is a
    no-op (and does not re-resolve `tool_config` for it)."""
    if meeting_id in _running:
        return

    agent = MeetingLiveAgent(room_name=room_name, meeting_id=meeting_id, tool_config=tool_config)
    task = asyncio.create_task(agent.run())
    task.add_done_callback(lambda t: _log_agent_task_result(t, meeting_id))
    _running[meeting_id] = (agent, task)
    logger.info(
        "live agent started meeting_id=%s room=%s languages=%s tool_config=%s",
        meeting_id, room_name, languages, tool_config,
    )


def _log_agent_task_result(task: asyncio.Task, meeting_id: str) -> None:
    """`agent.run()` runs as a fire-and-forget background task — nothing
    else in this module ever awaits or otherwise inspects it, so a crash
    partway through (bad LiveKit credentials, an invalid Gemini model
    name, a connection failure, ...) used to fail completely silently:
    the meeting proceeds normally (chat's plain original-text broadcast
    doesn't need the bot at all — see chat_relay.py's docstring), captions/
    dubbing/translated-chat just never happen, and nothing anywhere logs
    why. This callback is the only thing that ever looks at the task's
    outcome, so it's the one place that can surface that failure at all."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("live agent crashed meeting_id=%s — captions/dubbing/chat translation are NOT running for this meeting", meeting_id, exc_info=exc)
        asyncio.create_task(_report_agent_crash(meeting_id, exc))


async def _report_agent_crash(meeting_id: str, exc: BaseException) -> None:
    # No LiveKit broadcast here — the room connection that just died IS
    # the channel; the bot disappearing from useParticipants() is the
    # only live signal a still-connected client gets. translation_active
    # flipping False (and translation_error being set) is what a client
    # sees on its next fetch/re-join.
    await status.set_translation_active(meeting_id, False)
    await status.set_translation_error(meeting_id, f"Live translation crashed: {exc}")


async def stop_for_meeting(meeting_id: str) -> None:
    """Bounded wait, same as the old module, so a meeting-end request
    can't hang indefinitely on slow teardown (STT/TTS session close, etc)."""
    entry = _running.pop(meeting_id, None)
    if entry is None:
        return
    agent, task = entry
    agent.request_stop()
    try:
        await asyncio.wait_for(task, timeout=15)
    except asyncio.TimeoutError:
        logger.warning("live agent shutdown timed out meeting_id=%s — cancelling remaining task", meeting_id)
        task.cancel()
    logger.info("live agent stopped meeting_id=%s", meeting_id)
