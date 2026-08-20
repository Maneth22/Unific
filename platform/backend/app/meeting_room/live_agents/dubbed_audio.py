"""Live dubbed audio — Gemini 3.5 Live Translate
(`gemini-3.5-live-translate-preview`, via the Gemini Live API), NOT a
separate STT-text-translate-TTS chain. A single audio-in/audio-out model
per active target language, entirely independent of captions.py's STT
pipeline and translator.py's text-translation pipeline (which back
captions/chat only) — no TTS provider is used or needed anywhere in this
module.

One shared `translated-<lang>` track per active target language — never
per listener — same demand-driven shape `DubbedAudioManager.sync()`
always had: it reconciles which languages are actually wanted (any
participant with `audio_mode=dubbed_audio` and that `caption_language`)
and starts/stops `LanguageAudioPipeline`s to match.

What's new: each active language's Gemini Live session needs a
continuous raw-audio INPUT stream, and a meeting can have more than one
person talking over its lifetime — so every active pipeline is fed by
whichever participant is CURRENTLY the room's active speaker (LiveKit's
own `active_speakers_changed` detection, forwarded here by
orchestrator.py), not a fixed "host" track. `DubbedAudioManager` owns
exactly ONE subscription to the current active speaker's mic track (the
`_bridge_loop`) and fans each frame out to every active language's
Gemini session — avoids N redundant subscriptions to the same track for
N active languages.
"""
from __future__ import annotations

import asyncio
import logging

from livekit import rtc

from app.config import settings
from app.meeting_room.live_agents.participant_attrs import ParticipantRegistry
from app.meeting_room.live_agents.status import TranslationErrorScope

logger = logging.getLogger("live_agents.dubbed_audio")

DUBBED_TRACK_NAME_PREFIX = "translated-"

# Gemini Live's own fixed wire formats (see live-translate docs) — not
# configurable, not the same rate both directions.
_INPUT_SAMPLE_RATE = 16000
_OUTPUT_SAMPLE_RATE = 24000

# LanguageAudioPipeline._supervise's reconnect tuning — see that method's
# own docstring. A single blip (network hiccup, Gemini closing a session
# at its own duration limit) self-heals silently; only a SUSTAINED run of
# failures gets surfaced to on_error.
_FAILURE_REPORT_THRESHOLD = 3
_MAX_BACKOFF_SECONDS = 15


class LanguageAudioPipeline:
    """One per active target language. Owns the published
    `translated-<lang>` track (created once, for this pipeline's whole
    life) and a self-healing Gemini Live Translate SESSION underneath it
    (opened, closed, and reopened as many times as needed — see
    `_supervise` — without ever touching the track or the caller-visible
    "this language is active" state). Never subscribes to any LiveKit
    track itself — `DubbedAudioManager`'s active-speaker bridge pushes
    raw input audio in via `feed_audio`."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        target_lang: str,
        translate_semaphore: asyncio.Semaphore,
        on_error=None,  # Callable[[TranslationErrorScope, str, str], None] — (scope, subject, detail), optional
        on_recovered=None,  # Callable[[TranslationErrorScope, str], None] — (scope, subject), optional
    ) -> None:
        self._room = room
        self._target_lang = target_lang
        self._translate_semaphore = translate_semaphore
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._sem_acquired = False
        self._audio_source: rtc.AudioSource | None = None
        self._publication: rtc.LocalTrackPublication | None = None
        self._session_cm = None
        self._session = None
        self._consecutive_failures = 0
        self._start_task: asyncio.Task | None = None
        self._stopped = False

    def launch(self) -> asyncio.Task:
        """Same launch()/stop() shape as SpeakerSTTSession — tracks the
        background start() task so stop() can cancel it cleanly (and
        still release the semaphore / unpublish / close whatever got as
        far as being created) even if called while still mid-startup.
        This task now runs for the pipeline's ENTIRE life (setup, then
        the indefinite _supervise() reconnect loop), not just a one-shot
        session open."""
        self._start_task = asyncio.create_task(self.start())
        return self._start_task

    async def start(self) -> None:
        await self._translate_semaphore.acquire()
        self._sem_acquired = True

        track_name = f"{DUBBED_TRACK_NAME_PREFIX}{self._target_lang}"
        try:
            self._audio_source = rtc.AudioSource(_OUTPUT_SAMPLE_RATE, 1)
            local_track = rtc.LocalAudioTrack.create_audio_track(track_name, self._audio_source)
            self._publication = await self._room.local_participant.publish_track(
                local_track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
        except Exception as exc:
            logger.exception("failed to publish dubbed-audio track lang=%s", self._target_lang)
            if self._on_error is not None:
                self._on_error(TranslationErrorScope.language, self._target_lang, str(exc))
            if self._sem_acquired:
                self._translate_semaphore.release()
                self._sem_acquired = False
            return
        logger.info("dubbed-audio (Gemini Live Translate) pipeline started lang=%s track=%s", self._target_lang, track_name)

        await self._supervise()

    async def feed_audio(self, pcm_bytes: bytes) -> None:
        """Called by DubbedAudioManager's active-speaker bridge, once per
        audio frame from whoever is currently talking. Silently drops
        frames if the session isn't up yet/anymore (mid-reconnect, or not
        started) — best-effort, same philosophy as everywhere else in
        this pipeline; a dropped input frame just means a brief gap in
        translation, not a crash, and NOT queued/replayed once the
        session comes back (stale audio would just desync further)."""
        if self._session is None or self._stopped:
            return
        from google.genai import types

        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_bytes, mime_type=f"audio/pcm;rate={_INPUT_SAMPLE_RATE}")
            )
        except Exception:
            logger.exception("failed to feed audio into Gemini Live Translate session lang=%s", self._target_lang)

    async def _supervise(self) -> None:
        """Keeps the Gemini Live SESSION alive across any number of
        reconnects — the published TRACK (start() above) never gets torn
        down or re-created; only the underlying translation session
        cycles underneath it, so the meeting's "Translator is here"
        presence (TranslatorParticipant.jsx) never flickers off just
        because one session round dropped.

        Retries indefinitely with capped exponential backoff — only
        stop() ends this loop, it never gives up on its own. A session
        ending is treated as "reconnect needed" whether it ends via an
        exception OR the receive() stream just completing cleanly (e.g.
        Gemini closing the session at its own duration limit) — both are
        "no longer translating," the caller doesn't get to tell the
        difference from outside.

        A single blip self-heals silently (log-only) — only once
        _FAILURE_REPORT_THRESHOLD consecutive attempts have failed does
        this actually call on_error; the moment a session opens
        successfully after that threshold was crossed, on_recovered
        fires once and the counter resets."""
        while not self._stopped:
            try:
                # Deferred to here, not module import time — google-genai
                # is real weight to load into every process at boot even
                # on a deployment that never touches live dubbing in a
                # given run (e.g. most test runs), same lazy-import
                # reasoning providers.py's module docstring documents for
                # its own SDKs.
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=settings.gemini_api_key)
                config = types.LiveConnectConfig(
                    response_modalities=["AUDIO"],
                    translation_config=types.TranslationConfig(target_language_code=self._target_lang),
                )
                session_cm = client.aio.live.connect(model=settings.live_agents_live_translate_model, config=config)
                self._session = await session_cm.__aenter__()
                self._session_cm = session_cm
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._handle_reconnect_failure(exc)
                continue

            was_previously_reported = self._consecutive_failures >= _FAILURE_REPORT_THRESHOLD
            self._consecutive_failures = 0
            if was_previously_reported and self._on_recovered is not None:
                self._on_recovered(TranslationErrorScope.language, self._target_lang)

            try:
                async for response in self._session.receive():
                    if self._stopped:
                        break
                    server_content = response.server_content
                    if server_content is None or server_content.model_turn is None:
                        continue
                    for part in server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            data = part.inline_data.data
                            frame = rtc.AudioFrame(data, _OUTPUT_SAMPLE_RATE, 1, len(data) // 2)
                            await self._audio_source.capture_frame(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._close_session()
                if self._stopped:
                    break
                await self._handle_reconnect_failure(exc)
                continue
            else:
                await self._close_session()
                if self._stopped:
                    break
                await self._handle_reconnect_failure(RuntimeError("Gemini Live Translate session ended"))

    async def _handle_reconnect_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures == _FAILURE_REPORT_THRESHOLD:
            logger.error(
                "Gemini Live Translate session repeatedly failing lang=%s (attempt %d) — reporting",
                self._target_lang, self._consecutive_failures, exc_info=exc,
            )
            if self._on_error is not None:
                self._on_error(TranslationErrorScope.language, self._target_lang, str(exc))
        else:
            logger.warning(
                "Gemini Live Translate session failed lang=%s attempt=%d — retrying: %s",
                self._target_lang, self._consecutive_failures, exc,
            )
        delay = min(2 ** (self._consecutive_failures - 1), _MAX_BACKOFF_SECONDS)
        await asyncio.sleep(delay)

    async def _close_session(self) -> None:
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                logger.exception("error closing Gemini Live Translate session lang=%s", self._target_lang)
        self._session = None
        self._session_cm = None

    async def stop(self) -> None:
        self._stopped = True
        if self._start_task is not None:
            self._start_task.cancel()
            try:
                await self._start_task
            except (asyncio.CancelledError, Exception):
                pass

        await self._close_session()

        if self._publication is not None:
            try:
                await self._room.local_participant.unpublish_track(self._publication.sid)
            except Exception:
                logger.exception("error unpublishing dubbed-audio track lang=%s", self._target_lang)

        if self._sem_acquired:
            self._translate_semaphore.release()
            self._sem_acquired = False

        logger.info("dubbed-audio pipeline stopped lang=%s", self._target_lang)


class DubbedAudioManager:
    """Per-meeting demand tracker — one `LanguageAudioPipeline` per
    language currently requested by at least one dubbed_audio participant,
    all fed by the one shared active-speaker audio bridge below."""

    def __init__(
        self, *, room: rtc.Room, registry: ParticipantRegistry, translate_semaphore: asyncio.Semaphore,
        on_error=None,  # Callable[[TranslationErrorScope, str, str], None], optional
        on_recovered=None,  # Callable[[TranslationErrorScope, str], None], optional
    ):
        self._room = room
        self._registry = registry
        self._translate_semaphore = translate_semaphore
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._pipelines: dict[str, LanguageAudioPipeline] = {}
        self._active_speaker_identity: str | None = None
        self._bridge_task: asyncio.Task | None = None

    def sync(self) -> None:
        needed = self._registry.distinct_dubbed_languages()
        active = set(self._pipelines.keys())

        added_any = False
        for lang in needed - active:
            pipeline = LanguageAudioPipeline(
                room=self._room, target_lang=lang, translate_semaphore=self._translate_semaphore,
                on_error=self._on_error, on_recovered=self._on_recovered,
            )
            # Registered immediately (before start() has even run), not
            # after — so a stop() issued while this pipeline is still
            # starting can still find it and clean up whatever got as far
            # as being created (semaphore/session/track), instead of
            # leaking it.
            self._pipelines[lang] = pipeline
            pipeline.launch()
            added_any = True

        for lang in active - needed:
            pipeline = self._pipelines.pop(lang, None)
            if pipeline is not None:
                asyncio.create_task(pipeline.stop())

        # A language becoming the first-ever demand mid-call, after
        # someone's already been identified as the active speaker, needs
        # the bridge started for them now — on_active_speakers_changed
        # only fires on a CHANGE of speaker, which may not happen again
        # for a while.
        if added_any and self._bridge_task is None and self._active_speaker_identity is not None:
            self._start_bridge(self._active_speaker_identity)

    def on_active_speakers_changed(self, speakers: list[rtc.Participant]) -> None:
        """`speakers` is LiveKit's own ranked, possibly-empty active-
        speaker list. Ignores the bot's own identity (its dubbed-audio
        publish tracks are SOURCE_MICROPHONE too, but orchestrator.py
        never reports the bot as a speaker to begin with — this check is
        defense in depth, not load-bearing) and re-points the shared
        bridge at whichever real participant is now first."""
        new_identity = None
        for participant in speakers:
            if participant.identity == settings.live_agents_bot_identity:
                continue
            new_identity = participant.identity
            break

        if new_identity == self._active_speaker_identity:
            return
        self._active_speaker_identity = new_identity

        if self._bridge_task is not None:
            self._bridge_task.cancel()
            self._bridge_task = None

        if new_identity is None or not self._pipelines:
            return
        self._start_bridge(new_identity)

    def _start_bridge(self, identity: str) -> None:
        participant = self._room.remote_participants.get(identity)
        if participant is None:
            return
        track = None
        for publication in participant.track_publications.values():
            if publication.kind == rtc.TrackKind.KIND_AUDIO and publication.source == rtc.TrackSource.SOURCE_MICROPHONE:
                track = publication.track
                break
        if track is None:
            return
        self._bridge_task = asyncio.create_task(self._bridge_loop(track, identity))

    async def _bridge_loop(self, track: rtc.Track, identity: str) -> None:
        audio_stream = rtc.AudioStream(track, sample_rate=_INPUT_SAMPLE_RATE, num_channels=1)
        try:
            async for event in audio_stream:
                pcm_bytes = bytes(event.frame.data)
                # Skip any pipeline whose target language already matches
                # what this speaker is speaking — that's a same-language
                # no-op "translation" nobody asked for (anyone wanting
                # this language already hears the speaker's raw track),
                # just wasted Gemini load on every single utterance.
                # Re-read fresh per frame (not cached at bridge-start) so
                # a speaker changing their own spoken_language mid-turn
                # doesn't leave this stale.
                speaker_settings = self._registry.get(identity)
                spoken_lang = speaker_settings.spoken_language if speaker_settings else None
                await asyncio.gather(
                    *(
                        pipeline.feed_audio(pcm_bytes)
                        for lang, pipeline in self._pipelines.items()
                        if lang != spoken_lang
                    ),
                    return_exceptions=True,
                )
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await audio_stream.aclose()
            except Exception:
                logger.exception("error closing active-speaker audio bridge stream")

    async def stop_all(self) -> None:
        if self._bridge_task is not None:
            self._bridge_task.cancel()
            try:
                await self._bridge_task
            except (asyncio.CancelledError, Exception):
                pass
            self._bridge_task = None
        for pipeline in list(self._pipelines.values()):
            await pipeline.stop()
        self._pipelines.clear()
