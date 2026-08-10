"""Real-time speech-to-speech translation for LiveKit meeting rooms.

Bidirectional by construction: one `TranslationAgent` per target language
joins the room as a bot (identity `{prefix}-{lang}`) and translates every
*other* real participant's microphone audio into that language — except a
participant who already speaks it (per their `language` participant
attribute, broadcast by the frontend via `localParticipant.setAttributes`),
which it skips. Running one agent per language in
`settings.live_translation_allowed_language_list` for a meeting therefore
gives every participant, regardless of which language they speak, a track
in their own language for everyone else — each listener's frontend then
renders either a speaker's original mic (same language) or the matching
bot's translated track (different language); see
`SelectiveAudioRenderer.jsx`.

`start_for_meeting`/`stop_for_meeting` are the orchestration entry points,
called from `services.py` on meeting go-live / end — one asyncio task per
language, running in-process inside the FastAPI server (no subprocess).

`scripts/translation_agent.py` is a thin CLI wrapper around
`TranslationAgent` for manually running/debugging a single language against
a single room outside the meeting lifecycle.
"""
from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types
from livekit import api as lk_api
from livekit import rtc

from app.config import settings

logger = logging.getLogger("translation_agent")

INPUT_SAMPLE_RATE = 16_000
INPUT_NUM_CHANNELS = 1
INPUT_FRAME_MS = 100  # ~3200 bytes/frame at 16kHz mono 16-bit, per Gemini's guidance

OUTPUT_SAMPLE_RATE = 24_000
OUTPUT_NUM_CHANNELS = 1

# One fixed prebuilt voice per target language, so every translation into
# that language sounds like the same speaker throughout the meeting,
# regardless of who's actually talking or how many separate Gemini sessions
# end up producing it. Names are Gemini Live's built-in voices (verified
# against the live API directly — see the "Kore" connectivity test); any
# other prebuilt name from that set works the same way if you want to swap
# one out.
VOICE_BY_LANGUAGE = {
    "en": "Puck",
    "si": "Kore",
    "ta": "Charon",
    "hi": "Fenrir",
}
DEFAULT_VOICE = "Puck"


class ParticipantTranslator:
    """Owns exactly one subscribed remote microphone track: reads it via an
    AudioStream, owns one Gemini Live session, and lazily publishes one
    outbound translated LocalAudioTrack the first time Gemini returns audio.

    One Gemini session per speaker (not one shared session for the whole
    room) — interleaving two different speakers' PCM into a single session
    would produce garbled, cross-talk translation, and per-speaker isolation
    means one speaker's bad audio/session error doesn't take down
    translation for everyone else in the room.
    """

    def __init__(
        self,
        *,
        room: rtc.Room,
        participant: rtc.RemoteParticipant,
        track: rtc.RemoteAudioTrack,
        target_lang: str,
        genai_client: genai.Client,
        model: str,
    ) -> None:
        self._room = room
        self._participant = participant
        self._track = track
        self._target_lang = target_lang
        self._genai_client = genai_client
        self._model = model

        self._audio_stream: rtc.AudioStream | None = None
        self._session_cm = None
        self._session = None
        self._audio_source: rtc.AudioSource | None = None
        self._publication: rtc.LocalTrackPublication | None = None
        self._send_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._sent_chunks = 0

    async def start(self) -> None:
        """Opens the audio stream and the Gemini session, then spawns the
        input/output pump loops as background tasks."""
        self._audio_stream = rtc.AudioStream(
            self._track,
            sample_rate=INPUT_SAMPLE_RATE,
            num_channels=INPUT_NUM_CHANNELS,
            frame_size_ms=INPUT_FRAME_MS,
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            translation_config=types.TranslationConfig(
                target_language_code=self._target_lang,
                echo_target_language=True,
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=VOICE_BY_LANGUAGE.get(self._target_lang, DEFAULT_VOICE)
                    )
                )
            ),
        )
        self._session_cm = self._genai_client.aio.live.connect(model=self._model, config=config)
        self._session = await self._session_cm.__aenter__()
        logger.info(
            "Gemini connected participant=%s target_lang=%s",
            self._participant.identity,
            self._target_lang,
        )

        self._send_task = asyncio.create_task(self._pump_input())
        self._recv_task = asyncio.create_task(self._pump_output())

    async def _pump_input(self) -> None:
        """Reads 16kHz mono 100ms PCM frames from LiveKit and streams them to
        Gemini. A single bad chunk is logged and skipped rather than killing
        the whole pipeline for this speaker."""
        try:
            async for event in self._audio_stream:
                frame = event.frame
                pcm_bytes = bytes(frame.data)
                try:
                    await self._session.send_realtime_input(
                        audio=types.Blob(data=pcm_bytes, mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE}")
                    )
                except Exception:
                    logger.exception(
                        "failed to send audio chunk to Gemini participant=%s", self._participant.identity
                    )
                    continue
                self._sent_chunks += 1
                if self._sent_chunks % 50 == 0:  # ~5s of audio at 100ms/chunk — avoid log spam
                    logger.info(
                        "audio sent to Gemini participant=%s chunks=%d",
                        self._participant.identity,
                        self._sent_chunks,
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("input pump crashed participant=%s", self._participant.identity)

    async def _pump_output(self) -> None:
        """Reads translated PCM audio back from Gemini (24kHz mono) and
        capture()s it into the published LiveKit track, publishing that
        track lazily on first audio."""
        try:
            async for response in self._session.receive():
                data = response.data
                if not data:
                    continue
                try:
                    await self._ensure_published()
                    samples_per_channel = len(data) // 2  # 16-bit samples
                    frame = rtc.AudioFrame(
                        data,
                        sample_rate=OUTPUT_SAMPLE_RATE,
                        num_channels=OUTPUT_NUM_CHANNELS,
                        samples_per_channel=samples_per_channel,
                    )
                    await self._audio_source.capture_frame(frame)
                except Exception:
                    logger.exception(
                        "failed to publish translated audio participant=%s", self._participant.identity
                    )
                    continue
                logger.debug(
                    "translation audio received participant=%s bytes=%d",
                    self._participant.identity,
                    len(data),
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("output pump crashed participant=%s", self._participant.identity)

    async def _ensure_published(self) -> None:
        if self._publication is not None:
            return
        self._audio_source = rtc.AudioSource(OUTPUT_SAMPLE_RATE, OUTPUT_NUM_CHANNELS)
        track_name = f"translated-{self._target_lang}-{self._participant.identity}"
        local_track = rtc.LocalAudioTrack.create_audio_track(track_name, self._audio_source)
        self._publication = await self._room.local_participant.publish_track(
            local_track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        logger.info(
            "translated track published participant=%s target_lang=%s track=%s",
            self._participant.identity,
            self._target_lang,
            track_name,
        )

    async def stop(self) -> None:
        """Cancels both pump tasks, exits the Gemini session, unpublishes the
        translated track, and closes the audio stream — each step isolated
        so one failure doesn't block the rest of cleanup."""
        for task in (self._send_task, self._recv_task):
            if task is not None:
                task.cancel()
        for task in (self._send_task, self._recv_task):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                logger.exception("error closing Gemini session participant=%s", self._participant.identity)

        if self._publication is not None:
            try:
                await self._room.local_participant.unpublish_track(self._publication.sid)
            except Exception:
                logger.exception("error unpublishing translated track participant=%s", self._participant.identity)

        if self._audio_stream is not None:
            try:
                await self._audio_stream.aclose()
            except Exception:
                logger.exception("error closing audio stream participant=%s", self._participant.identity)

        logger.info("translator stopped participant=%s", self._participant.identity)


class TranslationAgent:
    """One instance per target language per room. Translates every real
    participant *except* those whose own `language` attribute already
    matches `target_lang` — so running one agent per
    `settings.live_translation_allowed_language_list` entry gives bidirectional
    coverage: an English speaker's audio flows through the `si`/`ta`/`hi`
    agents (each skips it if the *listener's* — no, the *speaker's* —
    language already matches), while a Sinhala speaker's audio flows through
    the `en`/`ta`/`hi` agents. Nothing ever translates a language into
    itself.
    """

    def __init__(self, *, room_name: str, target_lang: str):
        self._room_name = room_name
        self._target_lang = target_lang
        self._room = rtc.Room()
        self._genai_client = genai.Client(api_key=settings.gemini_api_key)
        self._translators: dict[str, ParticipantTranslator] = {}
        # Tracks every real (non-bot) participant's current mic track/publication,
        # so a later language-attribute change can be re-evaluated without
        # needing to re-subscribe — see _sync_translator_for.
        self._speaker_tracks: dict[str, tuple[rtc.RemoteAudioTrack, rtc.RemoteTrackPublication, rtc.RemoteParticipant]] = {}
        self._bot_identity = f"{settings.live_translation_bot_identity_prefix}-{target_lang}"
        self._stopped = asyncio.Event()
        self._shutting_down = False

        self._room.on("participant_connected", self._on_participant_connected)
        self._room.on("participant_disconnected", self._on_participant_disconnected)
        self._room.on("track_subscribed", self._on_track_subscribed)
        self._room.on("track_unsubscribed", self._on_track_unsubscribed)
        self._room.on("participant_attributes_changed", self._on_participant_attributes_changed)
        self._room.on("disconnected", self._on_disconnected)

    async def run(self) -> None:
        token = (
            lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(self._bot_identity)
            .with_name(f"{self._target_lang.upper()} Translator")
            .with_grants(
                lk_api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=False,
                )
            )
        ).to_jwt()
        logger.info("bot token minted identity=%s room=%s", self._bot_identity, self._room_name)

        await self._room.connect(settings.livekit_url, token, rtc.RoomOptions(auto_subscribe=True))
        logger.info("LiveKit connected room=%s identity=%s", self._room_name, self._bot_identity)

        # auto_subscribe only covers tracks published *after* this point in
        # time — participants and publications that already existed when we
        # joined are added straight into room state from the initial join
        # response (see rtc.Room.connect), not through the live signaling
        # path that auto-subscribe hooks into, so no track_subscribed event
        # ever fires for them without an explicit subscribe request here.
        for participant in self._room.remote_participants.values():
            if self._is_bot_identity(participant.identity):
                continue
            logger.info("participant already in room identity=%s", participant.identity)
            for publication in participant.track_publications.values():
                if (
                    publication.kind == rtc.TrackKind.KIND_AUDIO
                    and publication.source == rtc.TrackSource.SOURCE_MICROPHONE
                    and not publication.subscribed
                ):
                    publication.set_subscribed(True)

        await self._stopped.wait()

        self._shutting_down = True
        for translator in list(self._translators.values()):
            await translator.stop()
        self._translators.clear()
        await self._room.disconnect()
        logger.info("LiveKit disconnected room=%s", self._room_name)

    def request_stop(self) -> None:
        self._stopped.set()

    def _is_bot_identity(self, identity: str) -> bool:
        return identity.startswith(settings.live_translation_bot_identity_prefix)

    def _speaker_language(self, participant: rtc.RemoteParticipant) -> str:
        return participant.attributes.get("language") or settings.live_translation_default_target_language

    def _sync_translator_for(
        self, participant: rtc.RemoteParticipant, track: rtc.RemoteAudioTrack, publication: rtc.RemoteTrackPublication
    ) -> None:
        """Starts or stops a translator for this speaker so the running
        state matches whether they currently need translating into
        `self._target_lang` — called on first subscribe and again whenever
        the speaker's `language` attribute changes, so switching languages
        mid-call (or setting it for the first time after joining) takes
        effect without a reconnect."""
        key = f"{participant.identity}:{publication.sid}"
        wants_translation = self._speaker_language(participant) != self._target_lang
        existing = self._translators.get(key)

        if wants_translation and existing is None:
            translator = ParticipantTranslator(
                room=self._room,
                participant=participant,
                track=track,
                target_lang=self._target_lang,
                genai_client=self._genai_client,
                model=settings.live_translation_model,
            )
            self._translators[key] = translator
            asyncio.create_task(translator.start())
            logger.info(
                "translation started participant=%s speaker_lang=%s target_lang=%s",
                participant.identity,
                self._speaker_language(participant),
                self._target_lang,
            )
        elif not wants_translation and existing is not None:
            del self._translators[key]
            asyncio.create_task(existing.stop())
            logger.info(
                "translation stopped (speaker now speaks target language) participant=%s target_lang=%s",
                participant.identity,
                self._target_lang,
            )

    def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        logger.info("participant joined identity=%s", participant.identity)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        logger.info("participant disconnected identity=%s", participant.identity)
        self._speaker_tracks.pop(participant.identity, None)
        stale_keys = [key for key in self._translators if key.startswith(f"{participant.identity}:")]
        for key in stale_keys:
            translator = self._translators.pop(key)
            asyncio.create_task(translator.stop())

    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if self._is_bot_identity(participant.identity):
            return  # never translate another translator's own output — feedback-loop guard
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if publication.source != rtc.TrackSource.SOURCE_MICROPHONE:
            return

        logger.info(
            "audio track subscribed participant=%s track_sid=%s", participant.identity, publication.sid
        )
        self._speaker_tracks[participant.identity] = (track, publication, participant)  # type: ignore[assignment]
        self._sync_translator_for(participant, track, publication)  # type: ignore[arg-type]

    def _on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        self._speaker_tracks.pop(participant.identity, None)
        key = f"{participant.identity}:{publication.sid}"
        translator = self._translators.pop(key, None)
        if translator is not None:
            asyncio.create_task(translator.stop())

    def _on_participant_attributes_changed(self, changed_attributes: dict, participant: rtc.Participant) -> None:
        if "language" not in changed_attributes or self._is_bot_identity(participant.identity):
            return
        known = self._speaker_tracks.get(participant.identity)
        if known is None:
            return  # no active mic track for them yet — nothing to (re)sync
        track, publication, tracked_participant = known
        logger.info(
            "participant language changed identity=%s language=%s", participant.identity, changed_attributes["language"]
        )
        self._sync_translator_for(tracked_participant, track, publication)

    def _on_disconnected(self, reason) -> None:
        if self._shutting_down:
            logger.info("room disconnected (shutdown) reason=%s", reason)
        else:
            logger.warning("room disconnected unexpectedly reason=%s", reason)
        self._stopped.set()


# ---------------------------------------------------------------------------
# Orchestration — one TranslationAgent task per allowed language, started
# when a meeting with translate_live=True goes live and stopped when it
# ends. In-memory registry: acceptable for a single-process dev/staging
# deployment (matches this feature's current scope); a backend restart mid-
# meeting drops tracking of any still-running agents along with it.
# ---------------------------------------------------------------------------

_running_agents: dict[str, list[TranslationAgent]] = {}
_running_tasks: dict[str, list[asyncio.Task]] = {}


async def start_for_meeting(room_name: str, meeting_id: str) -> None:
    """Starts one TranslationAgent per allowed language for this meeting's
    room, as background asyncio tasks in the current (FastAPI server) event
    loop. Idempotent — a second call for a meeting_id that's already running
    is a no-op, so this is safe to call from every join if desired."""
    if meeting_id in _running_agents:
        return

    agents: list[TranslationAgent] = []
    tasks: list[asyncio.Task] = []
    for lang in settings.live_translation_allowed_language_list:
        agent = TranslationAgent(room_name=room_name, target_lang=lang)
        task = asyncio.create_task(agent.run())
        agents.append(agent)
        tasks.append(task)

    _running_agents[meeting_id] = agents
    _running_tasks[meeting_id] = tasks
    logger.info(
        "live translation started meeting_id=%s room=%s languages=%s",
        meeting_id,
        room_name,
        settings.live_translation_allowed_language_list,
    )


async def stop_for_meeting(meeting_id: str) -> None:
    """Stops and awaits every translator task for this meeting, with a
    bounded wait so a meeting-end request can't hang indefinitely on a
    translator that's slow to clean up (Gemini session teardown, etc)."""
    agents = _running_agents.pop(meeting_id, None)
    tasks = _running_tasks.pop(meeting_id, None)
    if not agents or not tasks:
        return

    for agent in agents:
        agent.request_stop()
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=15)
    except asyncio.TimeoutError:
        logger.warning("live translation shutdown timed out meeting_id=%s — cancelling remaining tasks", meeting_id)
        for task in tasks:
            task.cancel()

    logger.info("live translation stopped meeting_id=%s", meeting_id)
