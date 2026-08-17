"""Optional live dubbed audio: one shared track per active target
language — never per listener, never per (speaker × language). Two
speakers who both need translating into the same language at the same
moment get sequenced back-to-back onto that one track via a per-language
queue + single writer task, not mixed — true sample-level audio mixing
of two overlapping synthetic voices would be less intelligible than
queued playback, so this is a deliberate design choice, not a shortcut.

`DubbedAudioManager.sync()` is the single choke point that recomputes
which languages are actually in demand (any participant with
`audio_mode=dubbed_audio` and that `caption_language`) and starts/stops
`LanguageAudioPipeline`s to match — called from every orchestrator event
that could change demand, so a participant flipping `audio_mode` or
`caption_language` mid-call starts or tears down a pipeline live, with no
reconnect needed.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from livekit import rtc

from app.meeting_room.live_agents.participant_attrs import ParticipantRegistry
from app.meeting_room.live_agents.providers import get_tts_for_language

logger = logging.getLogger("live_agents.dubbed_audio")

DUBBED_TRACK_NAME_PREFIX = "translated-"


@dataclass
class _Segment:
    text: str
    source_identity: str
    enqueued_at: float


class LanguageAudioPipeline:
    """One per active target language. Owns the queue, the shared
    `AudioSource`, and the published `translated-<lang>` track; a single
    writer task drains the queue in arrival order and synthesizes+
    publishes each segment before picking up the next one."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        target_lang: str,
        tts,
        queue_maxsize: int,
        tts_semaphore: asyncio.Semaphore,
    ) -> None:
        self._room = room
        self._target_lang = target_lang
        self._tts = tts
        self._tts_semaphore = tts_semaphore
        self._queue: asyncio.Queue[_Segment] = asyncio.Queue(maxsize=queue_maxsize)
        self._audio_source: rtc.AudioSource | None = None
        self._publication: rtc.LocalTrackPublication | None = None
        self._writer_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._sem_acquired = False
        self._dropped_count = 0

    def launch(self) -> asyncio.Task:
        """Same launch()/stop() shape as SpeakerSTTSession — tracks the
        background start() task so stop() can cancel it cleanly (and
        still release the semaphore / unpublish whatever got as far as
        being created) even if called while still queued/mid-startup."""
        self._start_task = asyncio.create_task(self.start())
        return self._start_task

    async def start(self) -> None:
        await self._tts_semaphore.acquire()
        self._sem_acquired = True

        self._audio_source = rtc.AudioSource(self._tts.sample_rate, self._tts.num_channels)
        track_name = f"{DUBBED_TRACK_NAME_PREFIX}{self._target_lang}"
        local_track = rtc.LocalAudioTrack.create_audio_track(track_name, self._audio_source)
        self._publication = await self._room.local_participant.publish_track(
            local_track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        self._writer_task = asyncio.create_task(self._writer_loop())
        logger.info("dubbed-audio pipeline started lang=%s track=%s", self._target_lang, track_name)

    def enqueue(self, text: str, *, source_identity: str) -> None:
        """Drop-newest-when-full: rejecting the incoming segment bounds
        worst-case backlog latency; evicting an already-queued older
        segment instead would produce gappy/out-of-order dubbed audio,
        which is worse."""
        try:
            self._queue.put_nowait(_Segment(text=text, source_identity=source_identity, enqueued_at=time.monotonic()))
        except asyncio.QueueFull:
            self._dropped_count += 1
            logger.warning(
                "dubbed-audio queue full lang=%s — dropping newest segment (dropped_total=%d)",
                self._target_lang, self._dropped_count,
            )

    async def _writer_loop(self) -> None:
        try:
            while True:
                segment = await self._queue.get()
                t0 = time.monotonic()
                try:
                    async with self._tts.synthesize(segment.text) as stream:
                        async for audio in stream:
                            await self._audio_source.capture_frame(audio.frame)
                except Exception:
                    logger.exception("TTS synthesis failed lang=%s", self._target_lang)
                    continue
                logger.info(
                    "dubbed-audio tts_ms=%d lang=%s source=%s queue_wait_ms=%d",
                    (time.monotonic() - t0) * 1000, self._target_lang, segment.source_identity,
                    (t0 - segment.enqueued_at) * 1000,
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("dubbed-audio writer loop crashed lang=%s", self._target_lang)

    async def stop(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._writer_task is not None:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._publication is not None:
            try:
                await self._room.local_participant.unpublish_track(self._publication.sid)
            except Exception:
                logger.exception("error unpublishing dubbed-audio track lang=%s", self._target_lang)

        if self._sem_acquired:
            self._tts_semaphore.release()
            self._sem_acquired = False

        logger.info("dubbed-audio pipeline stopped lang=%s", self._target_lang)


class DubbedAudioManager:
    """Per-meeting demand tracker — one `LanguageAudioPipeline` per
    language currently requested by at least one dubbed_audio participant."""

    def __init__(self, *, room: rtc.Room, registry: ParticipantRegistry, tts_semaphore: asyncio.Semaphore, queue_maxsize: int):
        self._room = room
        self._registry = registry
        self._tts_semaphore = tts_semaphore
        self._queue_maxsize = queue_maxsize
        self._pipelines: dict[str, LanguageAudioPipeline] = {}

    def sync(self) -> None:
        # KNOWN LATENT RISK, not hit today: `sync()` is only ever called
        # when settings.live_agents_captions_enabled is True (see
        # orchestrator.py's gating on every call site) — while that flag
        # is False, this method never runs at all. If/when dubbed audio
        # is re-enabled, note that get_tts_for_language() below is a
        # SYNCHRONOUS, inline call on the shared event loop (unlike
        # captions.py's SpeakerSTTSession.start(), which now offloads its
        # own equivalent provider-construction call via asyncio.to_thread
        # specifically to avoid this) — a slow/hanging TTS client
        # constructor here would block the whole server the same way the
        # STT one used to. `sync()` would need to become async (and its
        # sync callers in orchestrator.py switched to `asyncio.create_
        # task(self._dubbed.sync())`) to apply the same fix here.
        needed = self._registry.distinct_dubbed_languages()
        active = set(self._pipelines.keys())

        for lang in needed - active:
            tts = get_tts_for_language(lang)
            if tts is None:
                logger.warning(
                    "audio_mode=dubbed_audio requested for lang=%s but it has no TTS provider "
                    "configured — degrading to captions_only for that language",
                    lang,
                )
                continue
            pipeline = LanguageAudioPipeline(
                room=self._room, target_lang=lang, tts=tts,
                queue_maxsize=self._queue_maxsize, tts_semaphore=self._tts_semaphore,
            )
            # Registered immediately (before start() has even run), not
            # after — so a stop() issued while this pipeline is still
            # starting can still find it and clean up whatever got as far
            # as being created (semaphore/track), instead of leaking it.
            self._pipelines[lang] = pipeline
            pipeline.launch()

        for lang in active - needed:
            pipeline = self._pipelines.pop(lang, None)
            if pipeline is not None:
                asyncio.create_task(pipeline.stop())

    def enqueue_if_active(self, target_lang: str, text: str, *, source_identity: str) -> None:
        pipeline = self._pipelines.get(target_lang)
        if pipeline is not None:
            pipeline.enqueue(text, source_identity=source_identity)

    async def stop_all(self) -> None:
        for pipeline in list(self._pipelines.values()):
            await pipeline.stop()
        self._pipelines.clear()
