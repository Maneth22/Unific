// Explicit mic capture constraints — applied everywhere the mic gets
// (re-)published: VideoCallRoom.jsx's initial auto-publish, CallControlBar's
// mic <TrackToggle>, and its device-error retry path. Without these,
// livekit-client's own defaults (echoCancellation/noiseSuppression/
// autoGainControl all `true`, from its DEFAULT_AUDIO_CAPTURE_DEFAULTS) is
// what actually shipped — the culprit was autoGainControl: the browser's
// AGC continuously boosts input toward a target loudness, which on a
// sensitive/close mic also boosts the noise floor into audible static
// once it's turned up far enough ("mic sensitivity too high" is exactly
// what AGC pumping sounds like). echoCancellation/noiseSuppression stay on
// — only AGC is disabled, which is the one of the three that amplifies
// rather than filters. Tradeoff: a genuinely quiet speaker/mic won't get
// auto-boosted anymore — if that becomes a real complaint, the fix is a
// per-user input gain slider, not turning AGC back on.
export const MIC_CAPTURE_OPTIONS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: false,
}

// Once a call's camera-participant count passes this, CallLayout auto-focuses
// the current active/dominant speaker (spotlight + filmstrip) instead of an
// ever-shrinking grid. Tune here — see CallLayout.jsx's speaker-focus effect.
export const SPEAKER_FOCUS_PARTICIPANT_THRESHOLD = 6

// LiveKitRoom fires both `onError` (the raw getUserMedia rejection, from its
// own internal setCameraEnabled/setMicrophoneEnabled call) and
// `onMediaDeviceFailure` (that same error, pre-classified into one of four
// buckets) for the exact same camera/mic problem — see
// MediaDeviceFailure.getFailure in livekit-client. Letting both drive the
// same banner produces a race and, worse, a raw browser message like
// "Requested device not found" paired with "try leaving and rejoining the
// call", which is actively wrong advice when there's simply no camera
// attached. `onMediaDeviceFailure`'s classification (and TrackToggle's own
// per-button onDeviceError, run through the same classifier) drives the
// device-error bubble instead; `onError` is left for genuine connection
// failures (bad token, signaling/network issues) and ignores the
// device-related DOMExceptions it also receives.
export const DEVICE_ERROR_NAMES = new Set([
  'NotFoundError',
  'DevicesNotFoundError',
  'NotAllowedError',
  'PermissionDeniedError',
  'NotReadableError',
  'TrackStartError',
  'OverconstrainedError',
])

export const DEVICE_FAILURE_MESSAGES = {
  NotFound: 'No camera or microphone was found on this device. Connect one, then hit retry.',
  PermissionDenied: 'Access was blocked. Allow camera/microphone permissions for this site in your browser settings, then retry.',
  DeviceInUse: 'Already in use by another app or browser tab (on Windows, only one tab can use a device at a time). Close it, then retry.',
  Other: 'Device error — try retrying, or leave and rejoin the call.',
}

// Identity the backend's live_agents bot (app/meeting_room/live_agents/
// orchestrator.py) connects under — ONE per meeting, not one per language
// like the old translator-{lang} design. Every dubbed-audio track and
// every caption/chat relay message comes from this one identity; per-
// language distinction now happens by *track name*
// (DUBBED_TRACK_NAME_PREFIX + lang), not by a different participant
// identity per language. Must match settings.live_agents_bot_identity in
// the backend's .env.
export const LIVE_AGENTS_BOT_IDENTITY = 'unific-agent'

// Participant attribute names — four distinct attributes, four distinct
// meanings, broadcast via localParticipant.setAttributes({...}). This is
// the deliberate fix for the old design's single overloaded `language`
// attribute, which conflated "what I speak" with "what I want to hear".
// Backend counterpart: app/meeting_room/live_agents/participant_attrs.py
// (must match these strings exactly).
export const ATTR_SPOKEN_LANGUAGE = 'spoken_language'
export const ATTR_CAPTION_LANGUAGE = 'caption_language'
export const ATTR_AUDIO_MODE = 'audio_mode'
export const ATTR_CHAT_LANGUAGE = 'chat_language'

export const AUDIO_MODE_CAPTIONS_ONLY = 'captions_only'
export const AUDIO_MODE_DUBBED_AUDIO = 'dubbed_audio'

// One shared dubbed-audio track per active target language, published as
// `${DUBBED_TRACK_NAME_PREFIX}${lang}` (e.g. "translated-si") from the one
// LIVE_AGENTS_BOT_IDENTITY participant — never per speaker, never per
// listener. See SelectiveAudioRenderer.jsx.
export const DUBBED_TRACK_NAME_PREFIX = 'translated-'

// LiveKit text-stream topics. CAPTION_TEXT_TOPIC/TRANSCRIBED_TRACK_ID_ATTR
// are unchanged from the earlier Gemini-piggyback captions design (kept
// deliberately so this frontend churn stays minimal) — captions are now
// server-targeted via destination_identities, so CaptionBar.jsx no longer
// needs to filter incoming messages by sender identity/language itself.
// CHAT_TOPIC is the same topic @livekit/components-react's prefab <Chat>
// would use by LiveKit's own convention — this app's ChatPanel.jsx sends
// on it directly instead of using that prefab, since it needs a custom
// JSON payload (message_id/source_language) and needs to render
// original+translated together, which the prefab doesn't support.
export const CAPTION_TEXT_TOPIC = 'lk.transcription'
export const TRANSCRIBED_TRACK_ID_ATTR = 'lk.transcribed_track_id'
export const CHAT_TOPIC = 'lk.chat'
export const CHAT_TRANSLATED_TOPIC = 'lk.chat.translated'

// Display labels for every language code the live_agents STT/TTS provider
// registry currently knows (backend's settings.live_agents_stt_provider_map
// keys — see app/meeting_room/live_agents/providers.py), keyed the same
// way. CallControlBar renders options from the meeting's own `languages`
// (JoinResponse.languages / Meeting.translate_languages — a per-meeting UX
// scope whitelist, see schemas.MAX_TRANSLATE_LANGUAGES), looking labels up
// here.
export const LANGUAGE_LABELS = {
  en: 'English',
  si: 'Sinhala',
  hi: 'Hindi',
}

// Small local comparator standing in for @livekit/components-core's
// isEqualTrackRef, which isn't re-exported from @livekit/components-react's
// public entry point (and isn't a declared dependency of this package —
// importing straight from the transitive core package would be a phantom
// dependency). Two track refs are "the same" for our pinning/carousel-filter
// purposes if they point at the same participant + source.
export function sameTrackRef(a, b) {
  if (!a || !b) return false
  return a.participant?.identity === b.participant?.identity && a.source === b.source
}
