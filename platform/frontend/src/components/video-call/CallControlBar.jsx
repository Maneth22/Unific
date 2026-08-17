import React, { useCallback, useEffect, useState } from 'react'
import { MediaDeviceFailure, Track } from 'livekit-client'
import { DisconnectButton, TrackToggle, useLocalParticipant } from '@livekit/components-react'
import DeviceErrorBubble from './DeviceErrorBubble'
import {
  ATTR_AUDIO_MODE,
  ATTR_CAPTION_LANGUAGE,
  ATTR_CHAT_LANGUAGE,
  ATTR_SPOKEN_LANGUAGE,
  AUDIO_MODE_CAPTIONS_ONLY,
  AUDIO_MODE_DUBBED_AUDIO,
  DEVICE_FAILURE_MESSAGES,
  LANGUAGE_LABELS,
  MIC_CAPTURE_OPTIONS,
} from './callConstants'

// Hand-built control bar (mic / camera / screen-share / chat / leave) in
// place of the <ControlBar> prefab, specifically so the mic and camera
// buttons can each own a positioned wrapper — that's what lets a device
// error render as a bubble anchored directly on the button it's about, in
// both directions (audioinput vs videoinput never overwrite each other).
export default function CallControlBar({
  deviceErrors,
  callSettings,
  updateCallSetting,
  availableLanguages,
  openInviteUrl,
  showChat,
  onToggleChat,
}) {
  const { localParticipant } = useLocalParticipant()
  const [inviteCopied, setInviteCopied] = useState(false)

  // Broadcasts four distinct LiveKit participant attributes — not one
  // overloaded `language` field like the old design. spoken_language is
  // what this participant speaks (drives their own STT server-side);
  // caption_language is what they want captions/dubbed-audio in;
  // audio_mode picks between the two; chat_language (only sent once the
  // user diverges it from caption_language — see the chat picker below)
  // is what they want to READ chat in. Every backend live_agents pipeline
  // reacts to a change here live, with no reconnect required (see
  // live_agents/orchestrator.py's participant_attributes_changed
  // handling). Requires the can_update_own_metadata grant on this
  // participant's token (see livekit_video_provider.py) — silently fails
  // otherwise, so wrapped.
  useEffect(() => {
    if (!localParticipant) return
    const attributes = {
      [ATTR_SPOKEN_LANGUAGE]: callSettings.spokenLanguage,
      [ATTR_CAPTION_LANGUAGE]: callSettings.captionLanguage,
      [ATTR_AUDIO_MODE]: callSettings.audioMode,
    }
    if (callSettings.chatLanguage) {
      attributes[ATTR_CHAT_LANGUAGE] = callSettings.chatLanguage
    }
    localParticipant.setAttributes(attributes).catch(() => {
      // Token missing can_update_own_metadata, or not connected yet —
      // captions/dubbing/chat translation simply won't route for this
      // participant; nothing else in the call depends on this succeeding.
    })
  }, [localParticipant, callSettings])

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

  // Copies the meeting's one shareable "anyone with this link can join"
  // link (see backend MeetingInviteKind.open) — visible to every
  // participant regardless of how they themselves joined, so someone who
  // joined via a personal link can still bring in a newcomer mid-call.
  const handleCopyInvite = useCallback(async () => {
    if (!openInviteUrl) return
    await navigator.clipboard.writeText(openInviteUrl)
    setInviteCopied(true)
    setTimeout(() => setInviteCopied(false), 1500)
  }, [openInviteUrl])

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

      {/* Two separate pickers where the old design had one — this is the
          actual fix for the "spoken vs preferred" conflation. Options are
          restricted to this meeting's own translate_languages (see
          VideoCallRoom's `languages` prop) — a per-meeting UX scope
          whitelist, not a resource-provisioning list under the new
          design (see backend schemas.MAX_TRANSLATE_LANGUAGES). */}
      <select
        className="cq-language-select"
        value={callSettings.spokenLanguage}
        onChange={(event) => updateCallSetting('spokenLanguage', event.target.value)}
        aria-label="Language you speak"
        title="Language you speak"
      >
        {availableLanguages.map((code) => (
          <option key={code} value={code}>
            🎤 {LANGUAGE_LABELS[code] || code}
          </option>
        ))}
      </select>

      <select
        className="cq-language-select"
        value={callSettings.captionLanguage}
        onChange={(event) => updateCallSetting('captionLanguage', event.target.value)}
        aria-label="Language you want captions/audio in"
        title="Language you want captions/audio in"
      >
        {availableLanguages.map((code) => (
          <option key={code} value={code}>
            💬 {LANGUAGE_LABELS[code] || code}
          </option>
        ))}
      </select>

      {/* Optional — defaults to caption_language server-side (see
          participant_attrs.ParticipantSettings.from_participant) if never
          touched, so this only actually broadcasts chat_language once the
          reader diverges it from what they picked above (e.g. they want
          captions in Sinhala but still prefer to read chat in English). */}
      <select
        className="cq-language-select"
        value={callSettings.chatLanguage || callSettings.captionLanguage}
        onChange={(event) => updateCallSetting('chatLanguage', event.target.value)}
        aria-label="Language you want to read chat in"
        title="Language you want to read chat in"
      >
        {availableLanguages.map((code) => (
          <option key={code} value={code}>
            📝 {LANGUAGE_LABELS[code] || code}
          </option>
        ))}
      </select>

      <label className="cq-audio-mode-toggle" title="Play synthesized dubbed audio in your caption language instead of just showing captions">
        <input
          type="checkbox"
          checked={callSettings.audioMode === AUDIO_MODE_DUBBED_AUDIO}
          onChange={(event) =>
            updateCallSetting('audioMode', event.target.checked ? AUDIO_MODE_DUBBED_AUDIO : AUDIO_MODE_CAPTIONS_ONLY)
          }
        />
        Dubbed audio
      </label>

      {openInviteUrl && (
        <button type="button" className="btn" onClick={handleCopyInvite}>
          {inviteCopied ? '✓ Copied' : 'Invite'}
        </button>
      )}

      <button type="button" className="btn" onClick={onToggleChat} aria-pressed={showChat}>
        Chat
      </button>
      <DisconnectButton className="cq-leave-btn">Leave</DisconnectButton>
    </div>
  )
}
