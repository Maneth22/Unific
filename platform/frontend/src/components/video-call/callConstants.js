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

// Identity prefix the backend translation bot (scripts/translation_agent.py)
// joins under, as `{TRANSLATOR_IDENTITY_PREFIX}-{lang}` (e.g. "translator-si").
// Must match LIVE_TRANSLATION_BOT_IDENTITY_PREFIX in the backend's .env.
// SelectiveAudioRenderer uses this to tell a translated track apart from a
// real participant's own microphone track.
export const TRANSLATOR_IDENTITY_PREFIX = 'translator'

// Languages the live-translation agent supports, keyed by the same codes the
// backend's LIVE_TRANSLATION_ALLOWED_LANGUAGES / Gemini's target_language_code
// use. 'en' means "no translation — play the original mic audio".
export const TRANSLATION_LANGUAGES = [
  { value: 'en', label: 'English (original)' },
  { value: 'si', label: 'Sinhala' },
  { value: 'ta', label: 'Tamil' },
  { value: 'hi', label: 'Hindi' },
]

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
