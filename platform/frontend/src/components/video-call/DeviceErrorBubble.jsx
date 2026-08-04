import React, { useCallback, useState } from 'react'

// Shared device-error state for the call controls, keyed by device kind so a
// camera problem and a microphone problem can be shown (and retried)
// independently without clobbering each other. Fed from two sources that can
// both fire for the same kind of device — see CallControlBar.jsx and
// VideoCallRoom.jsx — the last one to report simply overwrites that kind's
// entry, which is correct since it's always describing that device's current
// state.
export function useDeviceErrorState() {
  const [state, setState] = useState({ videoinput: null, audioinput: null })

  const setFailure = useCallback((kind, failure) => {
    if (!kind) return
    setState((s) => ({ ...s, [kind]: failure ?? null }))
  }, [])

  const clear = useCallback((kind) => {
    setState((s) => ({ ...s, [kind]: null }))
  }, [])

  return { videoinput: state.videoinput, audioinput: state.audioinput, setFailure, clear }
}

// A small speech-bubble anchored (via CSS, see video-call.css's .cq-btn-anchor
// / .cq-device-bubble) directly above the device button it's reporting on.
// No auto-dismiss — a device error is actionable, it shouldn't silently
// disappear before the user has a chance to retry or read it.
export default function DeviceErrorBubble({ message, onRetry, onDismiss }) {
  return (
    <div className="cq-device-bubble" role="alert">
      <div className="cq-device-bubble-arrow" />
      <p>{message}</p>
      <div className="cq-device-bubble-actions">
        <button type="button" className="btn cq-device-bubble-retry" onClick={onRetry}>
          Retry
        </button>
        <button type="button" className="cq-device-bubble-dismiss" aria-label="Dismiss" onClick={onDismiss}>
          ×
        </button>
      </div>
    </div>
  )
}
