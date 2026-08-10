import React, { useCallback, useEffect } from 'react'
import { MediaDeviceFailure, Track } from 'livekit-client'
import { ChatToggle, DisconnectButton, TrackToggle, useLocalParticipant } from '@livekit/components-react'
import DeviceErrorBubble from './DeviceErrorBubble'
import { DEVICE_FAILURE_MESSAGES, MIC_CAPTURE_OPTIONS, TRANSLATION_LANGUAGES } from './callConstants'

// Hand-built control bar (mic / camera / screen-share / chat / leave) in
// place of the <ControlBar> prefab, specifically so the mic and camera
// buttons can each own a positioned wrapper — that's what lets a device
// error render as a bubble anchored directly on the button it's about, in
// both directions (audioinput vs videoinput never overwrite each other).
export default function CallControlBar({ deviceErrors, preferredLanguage, setPreferredLanguage }) {
  const { localParticipant } = useLocalParticipant()

  // Broadcasts this participant's language as a LiveKit participant
  // attribute (not an API call to our own backend) — the one field that
  // doubles as both "what I speak" and "what I want to hear". The backend's
  // live_translation.py agents read it off every real participant to decide
  // who needs translating into which language; other participants'
  // SelectiveAudioRenderer reads it too, to decide whether to play a given
  // speaker's original mic or their translated track. Requires the
  // can_update_own_metadata grant on this participant's token (see
  // livekit_video_provider.py) — silently fails otherwise, so wrapped.
  useEffect(() => {
    if (!localParticipant) return
    localParticipant.setAttributes({ language: preferredLanguage }).catch(() => {
      // Token missing can_update_own_metadata, or not connected yet —
      // translation simply won't route for this participant; nothing else
      // in the call depends on this succeeding.
    })
  }, [localParticipant, preferredLanguage])

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
        else await localParticipant.setMicrophoneEnabled(true, MIC_CAPTURE_OPTIONS)
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
        <TrackToggle
          source={Track.Source.Microphone}
          captureOptions={MIC_CAPTURE_OPTIONS}
          onDeviceError={handleDeviceError('audioinput')}
        />
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

      {/* The one language field serving both roles: what this participant
          speaks and what they want to hear everyone else in. Broadcast via
          the effect above; SelectiveAudioRenderer combines it with every
          other participant's own broadcast language to decide, per remote
          track, whether to play their original mic or their translated
          track for *this* listener. */}
      <select
        className="cq-language-select"
        value={preferredLanguage}
        onChange={(event) => setPreferredLanguage(event.target.value)}
        aria-label="Listening language"
      >
        {TRANSLATION_LANGUAGES.map((language) => (
          <option key={language.value} value={language.value}>
            {language.label}
          </option>
        ))}
      </select>

      <ChatToggle>Chat</ChatToggle>
      <DisconnectButton className="cq-leave-btn">Leave</DisconnectButton>
    </div>
  )
}
