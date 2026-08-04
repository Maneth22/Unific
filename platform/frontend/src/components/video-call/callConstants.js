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
