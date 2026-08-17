"""Live, per-language-deduped captions.

One `SpeakerSTTSession` (a lightweight, STT-only `AgentSession`) per
active real speaker — `AgentSession`/`RoomIO` can only ever link to ONE
participant at a time (confirmed against LiveKit's own docs: "an agent
can interact with one participant at a time"), so per-speaker instances
are a hard requirement here, not a stylistic choice. Each session runs
`llm`/`tts` omitted entirely — matches LiveKit's own "Transcriber" recipe
pattern (STT + VAD only: "because there is no LLM/TTS, the agent never
speaks; it only records") — and only ever emits VAD-finalized transcripts
(`user_input_transcribed` where `is_final`); no word-level/mid-sentence
streaming translation is attempted, captions are segmented on end-of-turn.
This is a deliberate latency tradeoff (a full utterance's latency before
any translation starts) in exchange for not translating a transcript
fragment that Gemini would render inconsistently turn over turn.

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
from typing import TYPE_CHECKING

from livekit import rtc

from app.config import settings
from app.meeting_room.live_agents.participant_attrs import ParticipantRegistry
from app.meeting_room.live_agents.providers import UnsupportedLanguageError, get_shared_vad, get_stt_for_language
from app.meeting_room.live_agents.translator import TranslatorManager

if TYPE_CHECKING:
    from livekit.agents import AgentSession

logger = logging.getLogger("live_agents.captions")

# Same topic/attribute names the old live_translation.py's caption
# piggyback used — kept deliberately so the frontend's CaptionBar.jsx only
# needs its sender-identity filtering removed, not a topic rename.
CAPTION_TEXT_TOPIC = "lk.transcription"
TRANSCRIBED_TRACK_ID_ATTR = "lk.transcribed_track_id"


class SpeakerSTTSession:
    """Owns exactly one `AgentSession` scoped to one speaker via
    `RoomOptions.participant_identity`. STT is bound at session-start
    time — a `spoken_language` attribute change mid-call cannot hot-swap
    the STT plugin inside a running session, so `CaptionDispatcher`
    tears this down and starts a fresh one when that attribute changes
    (see `CaptionDispatcher.on_spoken_language_changed`)."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        participant: rtc.RemoteParticipant,
        spoken_language: str,
        on_final_transcript,  # async Callable[[str, str, str | None], None] — (speaker_identity, transcript, detected_lang)
        stt_semaphore: asyncio.Semaphore,
    ) -> None:
        self._room = room
        self._participant = participant
        self._spoken_language = spoken_language
        self._on_final_transcript = on_final_transcript
        self._stt_semaphore = stt_semaphore

        self._session: AgentSession | None = None
        self._sem_acquired = False
        self._start_task: asyncio.Task | None = None

    def launch(self) -> asyncio.Task:
        """Mirrors the old ParticipantTranslator.launch() pattern — tracks
        the background start() task so stop() can cancel it cleanly if
        it's still queued on the semaphore (or otherwise mid-startup)."""
        self._start_task = asyncio.create_task(self.start())
        return self._start_task

    async def start(self) -> None:
        try:
            # Off the event loop, not called inline: constructing an STT
            # client can synchronously touch the network (most notably
            # Google's client libraries, which fall back to querying the
            # GCP metadata server when no explicit credentials are
            # configured, and can hang doing so on a non-GCP host). This
            # process runs everything — every HTTP request, every other
            # meeting's live agent — on one shared event loop, so a
            # blocking call made inline here would freeze the entire
            # server, not just this caption session, until restarted.
            stt = await asyncio.to_thread(get_stt_for_language, self._spoken_language)
        except UnsupportedLanguageError:
            logger.warning(
                "no STT provider for spoken_language=%s participant=%s — captions unavailable for them",
                self._spoken_language, self._participant.identity,
            )
            return
        except Exception:
            # Any other provider-construction failure (bad/missing
            # credentials, network error, ...) degrades the same way —
            # this participant just doesn't get captioned, instead of
            # taking down the whole agent task (and, since nothing else
            # was awaiting this task, doing so completely silently).
            logger.exception(
                "STT provider construction failed spoken_language=%s participant=%s — captions unavailable for them",
                self._spoken_language, self._participant.identity,
            )
            return

        await self._stt_semaphore.acquire()
        self._sem_acquired = True

        # Deferred to here rather than module import time — see
        # providers.py's module docstring for why livekit.agents/plugin
        # imports in this package are all lazy.
        from livekit.agents import Agent, AgentSession, room_io

        # Same off-event-loop reasoning as get_stt_for_language above —
        # get_shared_vad() calls Silero's VAD.load() the first time it's
        # ever invoked in this process, a synchronous ONNX model load.
        vad = await asyncio.to_thread(get_shared_vad)
        self._session = AgentSession(stt=stt, vad=vad)
        self._session.on("user_input_transcribed", self._handle_transcribed)

        await self._session.start(
            agent=Agent(instructions=""),
            room=self._room,
            room_options=room_io.RoomOptions(
                participant_identity=self._participant.identity,
                # This session only ever consumes STT events — it must
                # never auto-publish audio/text back, and must never
                # compete with chat_relay.py for the lk.chat text-input
                # topic (RoomOptions.text_input defaults to enabled).
                audio_output=False,
                text_output=False,
                text_input=False,
                video_input=False,
                # Multiple SpeakerSTTSessions share one rtc.Room connection
                # (see orchestrator.py) — none of them should contend to be
                # the room's single "primary"/recording session.
            ),
            session_host=False,
        )
        logger.info(
            "caption STT session started participant=%s spoken_language=%s",
            self._participant.identity, self._spoken_language,
        )

    def _handle_transcribed(self, ev) -> None:
        if not ev.is_final or not ev.transcript.strip():
            return
        asyncio.create_task(
            self._on_final_transcript(self._participant.identity, ev.transcript, ev.language)
        )

    async def stop(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._session is not None:
            try:
                await self._session.aclose()
            except Exception:
                logger.exception("error closing caption STT session participant=%s", self._participant.identity)

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
        on_translated_segment,  # Callable[[str, str, str], None] — (target_lang, translated_text, source_identity), for dubbed-audio enqueue
    ) -> None:
        self._room = room
        self._registry = registry
        self._translator = translator
        self._stt_semaphore = stt_semaphore
        self._on_translated_segment = on_translated_segment
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
            self._on_translated_segment(target_lang, translated, speaker_identity)

    async def stop_all(self) -> None:
        for session in list(self._sessions.values()):
            await session.stop()
        self._sessions.clear()
        self._track_sids.clear()
