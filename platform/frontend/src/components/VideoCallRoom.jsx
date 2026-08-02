import React, { useState } from 'react'
import { ConnectionStateToast, LiveKitRoom, StartAudio, VideoConference } from '@livekit/components-react'
import '@livekit/components-styles'

// LiveKitRoom fires both `onError` (the raw getUserMedia rejection, from its
// own internal setCameraEnabled/setMicrophoneEnabled call) and
// `onMediaDeviceFailure` (that same error, pre-classified into one of four
// buckets) for the exact same camera/mic problem — see
// MediaDeviceFailure.getFailure in livekit-client. Letting both drive the
// same banner produces a race and, worse, a raw browser message like
// "Requested device not found" paired with "try leaving and rejoining the
// call", which is actively wrong advice when there's simply no camera
// attached. `onMediaDeviceFailure`'s classification is used for messaging
// instead; `onError` is left for genuine connection failures (bad token,
// signaling/network issues) and ignores the device-related DOMExceptions it
// also receives.
const DEVICE_ERROR_NAMES = new Set([
  'NotFoundError',
  'DevicesNotFoundError',
  'NotAllowedError',
  'PermissionDeniedError',
  'NotReadableError',
  'TrackStartError',
  'OverconstrainedError',
])

const DEVICE_FAILURE_MESSAGES = {
  NotFound: 'No camera or microphone was found on this device. Connect one, then use the device menu in the call controls to try again — leaving and rejoining will not fix a missing device.',
  PermissionDenied: 'Camera/microphone access was blocked. Allow camera and microphone permissions for this site in your browser settings, then rejoin.',
  DeviceInUse: 'Your camera or microphone is already in use by another app or browser tab (on Windows, only one tab can use a device at a time). Close it and try again.',
  Other: 'Camera/microphone error — try leaving and rejoining the call.',
}

// Shared by every join surface (staff dashboard, client dashboard, and the
// public passwordless invite page) — one component, three token sources.
// `serverUrl`/`token` come straight from the backend's JoinResponse
// ({ livekit_url, token }); this component never talks to the LiveKit API
// itself, only to the room the backend already authorized.
export default function VideoCallRoom({ serverUrl, token, onDisconnected }) {
  const [callError, setCallError] = useState(null)

  if (!serverUrl || !token) {
    return (
      <div className="card" style={{ padding: 16, background: 'var(--red-bg)', color: 'var(--red)' }}>
        This meeting room isn't configured correctly (missing server URL or token) — it can't connect.
      </div>
    )
  }

  return (
    <LiveKitRoom
      serverUrl={serverUrl}
      token={token}
      connect
      video
      audio
      style={{ height: '80vh' }}
      onDisconnected={onDisconnected}
      onError={(err) => {
        if (DEVICE_ERROR_NAMES.has(err.name)) return
        setCallError(`Connection error: ${err.message} — try leaving and rejoining the call.`)
      }}
      onMediaDeviceFailure={(failure) =>
        setCallError(failure ? DEVICE_FAILURE_MESSAGES[failure] || DEVICE_FAILURE_MESSAGES.Other : null)
      }
    >
      {callError && (
        <div
          className="card"
          style={{ padding: '8px 12px', margin: '0 0 8px', background: 'var(--red-bg)', color: 'var(--red)' }}
        >
          {callError}
        </div>
      )}
      <ConnectionStateToast />
      <StartAudio label="Click to enable sound" />
      <VideoConference />
    </LiveKitRoom>
  )
}
