import React, { useCallback } from 'react'
import { MediaDeviceFailure, Track } from 'livekit-client'
import { ChatToggle, DisconnectButton, TrackToggle, useLocalParticipant } from '@livekit/components-react'
import DeviceErrorBubble from './DeviceErrorBubble'
import { DEVICE_FAILURE_MESSAGES } from './callConstants'

// Hand-built control bar (mic / camera / screen-share / chat / leave) in
// place of the <ControlBar> prefab, specifically so the mic and camera
// buttons can each own a positioned wrapper — that's what lets a device
// error render as a bubble anchored directly on the button it's about, in
// both directions (audioinput vs videoinput never overwrite each other).
export default function CallControlBar({ deviceErrors }) {
  const { localParticipant } = useLocalParticipant()

  const handleDeviceError = useCallback(
    (kind) => (error) => {
      deviceErrors.setFailure(kind, MediaDeviceFailure.getFailure(error))
    },
    [deviceErrors],
  )

  const retry = useCallback(
    (kind) => async () => {
      try {
        if (kind === 'videoinput') await localParticipant.setCameraEnabled(true)
        else await localParticipant.setMicrophoneEnabled(true)
        deviceErrors.clear(kind)
      } catch (err) {
        // Still failing — keep the bubble up, refresh the message in case the
        // failure reason changed (e.g. permission denied -> device in use).
        deviceErrors.setFailure(kind, MediaDeviceFailure.getFailure(err))
      }
    },
    [localParticipant, deviceErrors],
  )

  return (
    <div className="lk-control-bar cq-control-bar">
      <div className="cq-btn-anchor">
        <TrackToggle source={Track.Source.Microphone} onDeviceError={handleDeviceError('audioinput')} />
        {deviceErrors.audioinput && (
          <DeviceErrorBubble
            message={DEVICE_FAILURE_MESSAGES[deviceErrors.audioinput] || DEVICE_FAILURE_MESSAGES.Other}
            onRetry={retry('audioinput')}
            onDismiss={() => deviceErrors.clear('audioinput')}
          />
        )}
      </div>

      <div className="cq-btn-anchor">
        <TrackToggle source={Track.Source.Camera} onDeviceError={handleDeviceError('videoinput')} />
        {deviceErrors.videoinput && (
          <DeviceErrorBubble
            message={DEVICE_FAILURE_MESSAGES[deviceErrors.videoinput] || DEVICE_FAILURE_MESSAGES.Other}
            onRetry={retry('videoinput')}
            onDismiss={() => deviceErrors.clear('videoinput')}
          />
        )}
      </div>

      <TrackToggle source={Track.Source.ScreenShare} captureOptions={{ audio: true, selfBrowserSurface: 'include' }} />
      <ChatToggle>Chat</ChatToggle>
      <DisconnectButton className="cq-leave-btn">Leave</DisconnectButton>
    </div>
  )
}
