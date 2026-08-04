import React, { useCallback, useState } from 'react'
import { ConnectionStateToast, LiveKitRoom, StartAudio } from '@livekit/components-react'
import '@livekit/components-styles'
import './video-call.css'
import CallLayout from './CallLayout'
import { useDeviceErrorState } from './DeviceErrorBubble'
import { DEVICE_ERROR_NAMES } from './callConstants'

// Shared by every join surface (staff dashboard, staff portal, client
// dashboard, and the public passwordless invite page) — one component, four
// call sites, one token/serverUrl source each. `serverUrl`/`token` come
// straight from the backend's JoinResponse ({ livekit_url, token }); this
// component never talks to the LiveKit API itself, only to the room the
// backend already authorized.
export default function VideoCallRoom({ serverUrl, token, onDisconnected }) {
  const [callError, setCallError] = useState(null)
  const deviceErrors = useDeviceErrorState()

  // Stabilized with useCallback: LiveKitRoom's internal effects (see
  // useLiveKitRoom) list onError/onMediaDeviceFailure as dependencies, so an
  // inline function recreated every render caused those effects to tear down
  // and re-subscribe the room's event listeners on every callError update.
  // Harmless in practice (Room.connect() no-ops once already connected —
  // confirmed by reading livekit-client's Room.ts — so this was never the
  // cause of the "can't see others' video" bug below), but worth removing
  // while this file is already being rewritten.
  const handleError = useCallback((err) => {
    if (DEVICE_ERROR_NAMES.has(err.name)) return
    setCallError(`Connection error: ${err.message} — try leaving and rejoining the call.`)
  }, [])

  const handleMediaDeviceFailure = useCallback(
    (failure, kind) => {
      // kind is provided by the library, already classified via
      // MediaDeviceFailure.getFailure — feeds the same per-button bubble
      // state that CallControlBar's own TrackToggle.onDeviceError writes to,
      // so an initial-join failure and a later manual-retry failure for the
      // same device both show up the same way.
      if (kind) {
        deviceErrors.setFailure(kind, failure)
      } else {
        // No device kind to anchor to (rare) — fall back to the old
        // generic banner rather than dropping the error silently.
        setCallError(failure ? `Camera/microphone error (${failure}).` : null)
      }
    },
    [deviceErrors],
  )

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
      className="cq-call-room"
      // @livekit/components-styles' entire default theme (colors, spacing,
      // and layout-critical vars like --lk-control-bar-height/--lk-grid-gap)
      // is scoped under a [data-lk-theme] attribute selector — LiveKitRoom
      // never sets this itself, and this app never added it either. Without
      // it every --lk-* var used in the library's own CSS (including the
      // calc() that sizes the grid/focus area against the control bar) was
      // silently invalid, which is what collapsed/blew up the tile layout.
      data-lk-theme="default"
      onDisconnected={onDisconnected}
      onError={handleError}
      onMediaDeviceFailure={handleMediaDeviceFailure}
    >
      {callError && <div className="card cq-error-banner">{callError}</div>}
      <ConnectionStateToast />
      <StartAudio label="Click to enable sound" />
      <CallLayout deviceErrors={deviceErrors} />
    </LiveKitRoom>
  )
}
