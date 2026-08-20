"""Live, per-language-deduped captions.

One `SpeakerSTTSession` per active real speaker, talking directly to
Google Speech-to-Text v2's streaming `recognize` API (Chirp 3) — NOT
livekit-agents' `AgentSession`/`RoomIO`/VAD framework. That framework
pulls in `onnxruntime` (for VAD, and for its own default ML turn-detector
model, loaded regardless of whether `vad=` is even given — confirmed
directly), which crashes the whole process with an OS-level illegal-
instruction fault on any pre-AVX2 CPU. None of that machinery is needed
here anyway: this session only ever consumes raw mic audio and emits
final transcripts, no LLM/TTS turn to manage — Google's own streaming API
already reports `is_final` per utterance, doing its own end-of-turn
detection without a separate VAD pass.

Each session subscribes to its speaker's raw mic track via
`rtc.AudioStream` (resampled to 16kHz mono, LINEAR16 — what Chirp 3's
streaming config expects) and forwards frames straight into a
`StreamingRecognizeRequest` generator. No word-level/mid-sentence
streaming translation is attempted — only `result.is_final` results are
handed to `on_final_transcript`, captions are segmented on end-of-turn,
same tradeoff the old AgentSession-based version made (a full utterance's
latency before any translation starts, in exchange for not translating a
fragment Gemini would render inconsistently turn over turn).

`CaptionDispatcher` owns one `SpeakerSTTSession` per speaker and, on every
final transcript, translates it once per DISTINCT `caption_language`
currently needed among the room's other participants (never once per
listener — see `participant_attrs.ParticipantRegistry.
distinct_caption_languages`) and dispatches each translation only to the
identities that asked for it.
"""
from __future__ import annotations

import asyncio
import logging
import time

from livekit import rtc

from app.config import settings
from app.meeting_room.live_agents.participant_attrs import ParticipantRegistry
from app.meeting_room.live_agents.providers import (
    get_shared_speech_client,
    google_stt_recognizer_path,
    is_stt_language_supported,
    stt_model_and_location,
    stt_region_code,
)
from app.meeting_room.live_agents.status import TranslationErrorScope
from app.meeting_room.live_agents.translator import TranslatorManager

logger = logging.getLogger("live_agents.captions")

# How much audio each StreamingRecognizeRequest carries — small enough to
# keep latency low, large enough not to spam the gRPC stream with
# one-message-per-10ms overhead.
_STREAM_CHUNK_MS = 100
_STREAM_SAMPLE_RATE = 16000

# Same topic/attribute names the old live_translation.py's caption
# piggyback used — kept deliberately so the frontend's CaptionBar.jsx only
# needs its sender-identity filtering removed, not a topic rename.
CAPTION_TEXT_TOPIC = "lk.transcription"
TRANSCRIBED_TRACK_ID_ATTR = "lk.transcribed_track_id"

# Same self-healing-reconnect constants as dubbed_audio.py's
# LanguageAudioPipeline — see SpeakerSTTSession._supervise's own docstring
# for why this class needs the identical pattern.
_FAILURE_REPORT_THRESHOLD = 3
_MAX_BACKOFF_SECONDS = 15


def _is_expected_stream_rotation(exc: Exception) -> bool:
    """Google Speech-to-Text v2's streaming_recognize hard-caps every
    single stream at 5 minutes — confirmed live: a speaker active past
    that mark gets their stream closed with `409 ... Max duration of 5
    minutes reached for stream.` This is routine (any speaker in a call
    longer than 5 minutes hits it, every time), not a failure — excluded
    from the backoff/threshold/on_error path entirely so a normal meeting
    never surfaces a false alarm. Matched on Google's own message text
    rather than a specific exception type, since the SDK's own wrapping
    (google.api_core.exceptions subclass, transport-dependent) isn't
    guaranteed stable across versions."""
    return "max duration" in str(exc).lower()


class SpeakerSTTSession:
    """Owns one direct Google Speech-to-Text v2 streaming call scoped to
    one speaker's mic track. STT language is bound at session-start
    time — a `spoken_language` attribute change mid-call can't hot-swap
    the streaming config, so `CaptionDispatcher` tears this down and
    starts a fresh one when that attribute changes (see
    `CaptionDispatcher.on_spoken_language_changed`)."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        participant: rtc.RemoteParticipant,
        spoken_language: str,
        on_final_transcript,  # async Callable[[str, str, str | None], None] — (speaker_identity, transcript, detected_lang)
        stt_semaphore: asyncio.Semaphore,
        stt_map: dict[str, str] | None = None,
        on_error=None,  # Callable[[TranslationErrorScope, str, str], None] — (scope, subject, detail), optional
        on_recovered=None,  # Callable[[TranslationErrorScope, str], None] — (scope, subject), optional
    ) -> None:
        self._room = room
        self._participant = participant
        self._spoken_language = spoken_language
        self._on_final_transcript = on_final_transcript
        self._stt_semaphore = stt_semaphore
        # The meeting's resolved Tools Registry choice — see
        # tools_service.EffectiveToolConfig.meeting_stt. None falls back to
        # settings.live_agents_stt_provider_map_dict
        # (is_stt_language_supported's own default).
        self._stt_map = stt_map
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._consecutive_failures = 0

        self._audio_stream: rtc.AudioStream | None = None
        self._sem_acquired = False
        self._stopped = False
        self._start_task: asyncio.Task | None = None
        self._stream_task: asyncio.Task | None = None

    def launch(self) -> asyncio.Task:
        """Mirrors the old ParticipantTranslator.launch() pattern — tracks
        the background start() task so stop() can cancel it cleanly if
        it's still queued on the semaphore (or otherwise mid-startup)."""
        self._start_task = asyncio.create_task(self.start())
        return self._start_task

    async def start(self) -> None:
        if not is_stt_language_supported(self._spoken_language, self._stt_map):
            logger.warning(
                "no STT provider for spoken_language=%s participant=%s — captions unavailable for them",
                self._spoken_language, self._participant.identity,
            )
            if self._on_error is not None:
                self._on_error(
                    TranslationErrorScope.speaker, self._participant.identity,
                    f"no STT provider configured for language {self._spoken_language!r}",
                )
            return

        track = None
        for publication in self._participant.track_publications.values():
            if publication.kind == rtc.TrackKind.KIND_AUDIO and publication.source == rtc.TrackSource.SOURCE_MICROPHONE:
                track = publication.track
                break
        if track is None:
            # add_speaker only ever gets called with a live mic publication
            # in hand (see captions.py's own call sites) — this is a
            # defensive guard against a track that's already been
            # unpublished by the time this task actually runs, not an
            # expected path.
            logger.warning("no subscribed mic track found for participant=%s — captions unavailable", self._participant.identity)
            return

        await self._stt_semaphore.acquire()
        self._sem_acquired = True

        self._audio_stream = rtc.AudioStream(track, sample_rate=_STREAM_SAMPLE_RATE, num_channels=1)
        self._stream_task = asyncio.create_task(self._supervise())
        logger.info(
            "caption STT stream started participant=%s spoken_language=%s",
            self._participant.identity, self._spoken_language,
        )

    async def _request_generator(self, recognizer: str, model: str):
        from google.cloud.speech_v2.types import cloud_speech

        recognition_config = cloud_speech.RecognitionConfig(
            explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=_STREAM_SAMPLE_RATE, audio_channel_count=1,
            ),
            language_codes=[stt_region_code(self._spoken_language)], model=model,
        )
        endpointing_map = {
            "standard": cloud_speech.StreamingRecognitionFeatures.EndpointingSensitivity.ENDPOINTING_SENSITIVITY_STANDARD,
            "short": cloud_speech.StreamingRecognitionFeatures.EndpointingSensitivity.ENDPOINTING_SENSITIVITY_SHORT,
            "supershort": cloud_speech.StreamingRecognitionFeatures.EndpointingSensitivity.ENDPOINTING_SENSITIVITY_SUPERSHORT,
        }
        streaming_config = cloud_speech.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=cloud_speech.StreamingRecognitionFeatures(
                # No interim results consumed anywhere (only is_final
                # matters to this app — see module docstring), so don't
                # ask Google to send them at all.
                interim_results=False,
                # How quickly a pause gets treated as "end of utterance" —
                # confirmed live: "standard" (the unset default) took 23s
                # to emit its first is_final on a ~20s clip; "supershort"
                # cut that to ~7.5s and segmented naturally instead of one
                # giant block. See settings.live_agents_stt_endpointing_
                # sensitivity's own comment.
                endpointing_sensitivity=endpointing_map.get(
                    settings.live_agents_stt_endpointing_sensitivity,
                    cloud_speech.StreamingRecognitionFeatures.EndpointingSensitivity.ENDPOINTING_SENSITIVITY_SUPERSHORT,
                ),
            ),
        )
        yield cloud_speech.StreamingRecognizeRequest(recognizer=recognizer, streaming_config=streaming_config)
        assert self._audio_stream is not None
        async for event in self._audio_stream:
            if self._stopped:
                return
            yield cloud_speech.StreamingRecognizeRequest(audio=bytes(event.frame.data))

    async def _supervise(self) -> None:
        """Keeps this speaker captioned indefinitely across any number of
        underlying Google STT stream cycles — mirrors dubbed_audio.py's
        LanguageAudioPipeline._supervise, plus one extra branch that
        pattern doesn't need: Google's v2 streaming API hard-caps every
        single stream at 5 minutes (confirmed live: `409 ... Max duration
        of 5 minutes reached for stream.`), so ANY speaker active past
        that mark hits this, every time — routine stream rotation, not a
        failure (see `_is_expected_stream_rotation`), reconnected
        immediately with no backoff and no error report. A genuine
        failure (bad credentials, network error, the recognizer
        rejecting the config, ...) still gets the same backoff+threshold+
        recover treatment dubbed_audio.py's pipelines get — this
        participant just doesn't get captioned meanwhile, instead of
        taking down the whole agent task."""
        while not self._stopped:
            try:
                await self._open_and_consume_stream()
                # A clean generator exit (server closed the stream without
                # raising) still means "no longer captioned" — same
                # reconnect-needed treatment as an exception.
                raise RuntimeError("STT stream ended without an exception")
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self._stopped:
                    return
                if _is_expected_stream_rotation(exc):
                    logger.info(
                        "STT stream hit Google's 5-minute cap, reconnecting participant=%s spoken_language=%s",
                        self._participant.identity, self._spoken_language,
                    )
                    # No real backoff needed (this is routine, not a
                    # failure) — but still an actual await, not a bare
                    # `continue`: a synchronous-failing reconnect attempt
                    # (rare, but not impossible) would otherwise spin this
                    # loop with zero yield points and starve the event
                    # loop instead of just cycling quickly.
                    await asyncio.sleep(0)
                    continue
                await self._handle_reconnect_failure(exc)

    async def _handle_reconnect_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1
        logger.warning(
            "STT streaming failed (attempt %d) spoken_language=%s participant=%s: %s",
            self._consecutive_failures, self._spoken_language, self._participant.identity, exc,
        )
        if self._consecutive_failures == _FAILURE_REPORT_THRESHOLD and self._on_error is not None:
            self._on_error(TranslationErrorScope.speaker, self._participant.identity, str(exc))
        delay = min(2 ** (self._consecutive_failures - 1), _MAX_BACKOFF_SECONDS)
        await asyncio.sleep(delay)

    async def _open_and_consume_stream(self) -> None:
        # Sinhala needs a different model + region than everything
        # else (Chirp 3 doesn't support it in any GA location) — see
        # providers.stt_model_and_location's own docstring.
        model, location = stt_model_and_location(self._spoken_language)
        client = get_shared_speech_client(location)
        recognizer = google_stt_recognizer_path(location)
        responses = await client.streaming_recognize(requests=self._request_generator(recognizer, model))
        # The stream re-established successfully — if a prior failure on
        # this same session had actually crossed the report threshold
        # (and so was actually surfaced), clear it now rather than waiting
        # for a manual retry. A routine 5-minute rotation never crosses
        # the threshold in the first place, so this is a no-op for that
        # case, exactly as intended.
        if self._consecutive_failures >= _FAILURE_REPORT_THRESHOLD and self._on_recovered is not None:
            self._on_recovered(TranslationErrorScope.speaker, self._participant.identity)
        self._consecutive_failures = 0
        async for response in responses:
            for result in response.results:
                if not result.is_final or not result.alternatives:
                    continue
                transcript = result.alternatives[0].transcript.strip()
                if not transcript:
                    continue
                asyncio.create_task(
                    self._on_final_transcript(self._participant.identity, transcript, self._spoken_language)
                )

    async def stop(self) -> None:
        self._stopped = True
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._audio_stream is not None:
            try:
                await self._audio_stream.aclose()
            except Exception:
                logger.exception("error closing audio stream participant=%s", self._participant.identity)

        if self._sem_acquired:
            self._stt_semaphore.release()
            self._sem_acquired = False


class CaptionDispatcher:
    """Per-meeting: owns one `SpeakerSTTSession` per active speaker and
    dispatches every final transcript through the shared
    `TranslatorManager`, deduped by distinct `caption_language`."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        registry: ParticipantRegistry,
        translator: TranslatorManager,
        stt_semaphore: asyncio.Semaphore,
        stt_map: dict[str, str] | None = None,
        on_error=None,  # Callable[[TranslationErrorScope, str, str], None] — threaded into every SpeakerSTTSession
        on_recovered=None,  # Callable[[TranslationErrorScope, str], None] — threaded into every SpeakerSTTSession
    ) -> None:
        self._room = room
        self._registry = registry
        self._translator = translator
        self._stt_semaphore = stt_semaphore
        # The meeting's resolved Tools Registry choice (tools_service.
        # EffectiveToolConfig.meeting_stt), threaded into every
        # SpeakerSTTSession below — see that class's own docstring.
        self._stt_map = stt_map
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._sessions: dict[str, SpeakerSTTSession] = {}
        self._track_sids: dict[str, str] = {}  # speaker identity -> their mic track sid, for lk.transcribed_track_id

    def add_speaker(self, participant: rtc.RemoteParticipant, publication: rtc.RemoteTrackPublication) -> None:
        self._track_sids[participant.identity] = publication.sid
        if participant.identity in self._sessions:
            return
        settings_ = self._registry.get(participant.identity)
        spoken_lang = settings_.spoken_language if settings_ else settings.live_agents_default_language
        session = SpeakerSTTSession(
            room=self._room,
            participant=participant,
            spoken_language=spoken_lang,
            on_final_transcript=self._on_final_transcript,
            stt_semaphore=self._stt_semaphore,
            stt_map=self._stt_map,
            on_error=self._on_error,
            on_recovered=self._on_recovered,
        )
        self._sessions[participant.identity] = session
        session.launch()

    def remove_speaker(self, identity: str) -> None:
        self._track_sids.pop(identity, None)
        session = self._sessions.pop(identity, None)
        if session is not None:
            asyncio.create_task(session.stop())

    def on_spoken_language_changed(self, participant: rtc.RemoteParticipant) -> None:
        """STT is bound at session-start — restart this speaker's session
        under the new language rather than trying to hot-swap the plugin."""
        if participant.identity not in self._sessions:
            return  # no active mic track for them yet — nothing to restart
        self.remove_speaker(participant.identity)
        # remove_speaker() already dropped the track sid; re-derive it from
        # the participant's still-subscribed publication so add_speaker can
        # re-track it without a fresh track_subscribed event.
        for publication in participant.track_publications.values():
            if publication.kind == rtc.TrackKind.KIND_AUDIO and publication.source == rtc.TrackSource.SOURCE_MICROPHONE:
                self.add_speaker(participant, publication)
                break

    async def _on_final_transcript(self, speaker_identity: str, transcript: str, detected_lang: str | None) -> None:
        speaker_settings = self._registry.get(speaker_identity)
        source_lang = speaker_settings.spoken_language if speaker_settings else settings.live_agents_default_language
        stt_received_at = time.monotonic()

        grouped = self._registry.distinct_caption_languages(exclude_identity=speaker_identity)
        track_sid = self._track_sids.get(speaker_identity, "")

        for target_lang, recipients in grouped.items():
            t0 = time.monotonic()
            translated = await self._translator.translate(transcript, source_lang, target_lang)
            translate_ms = (time.monotonic() - t0) * 1000
            try:
                await self._room.local_participant.send_text(
                    translated,
                    topic=CAPTION_TEXT_TOPIC,
                    destination_identities=recipients,
                    attributes={TRANSCRIBED_TRACK_ID_ATTR: track_sid},
                )
            except Exception:
                logger.exception(
                    "failed to send caption speaker=%s target_lang=%s", speaker_identity, target_lang
                )
                continue
            logger.info(
                "caption dispatched speaker=%s source_lang=%s target_lang=%s recipients=%d "
                "stt_to_dispatch_ms=%d translate_ms=%d",
                speaker_identity, source_lang, target_lang, len(recipients),
                (time.monotonic() - stt_received_at) * 1000, translate_ms,
            )

    async def stop_all(self) -> None:
        for session in list(self._sessions.values()):
            await session.stop()
        self._sessions.clear()
        self._track_sids.clear()
