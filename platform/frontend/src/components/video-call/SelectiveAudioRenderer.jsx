import React from 'react'
import { RoomEvent, Track } from 'livekit-client'
import { AudioTrack, useTracks } from '@livekit/components-react'
import { TRANSLATOR_IDENTITY_PREFIX } from './callConstants'

// Replaces <RoomAudioRenderer/>, which plays every remote participant's
// audio track with no per-track control (confirmed: its only props are
// room-wide `volume`/`muted`). Bidirectional routing needs per-track
// decisions: for each other participant's mic track, this listener should
// hear either that speaker's *original* audio (if they already speak this
// listener's language, per the `language` attribute CallControlBar
// broadcasts) or the matching translator bot's track for them (if they
// don't) — never both, and never a different listener's language. A
// translator bot's own identity is exactly `${PREFIX}-${targetLang}`, so
// every track it publishes is already known to be in that one language,
// however many different speakers it's currently translating.
export default function SelectiveAudioRenderer({ preferredLanguage }) {
  const micTracks = useTracks([Track.Source.Microphone], {
    onlySubscribed: true,
    // useTracks already re-renders on track subscribe/unsubscribe by
    // default; this adds a re-render when a speaker's declared language
    // changes mid-call (e.g. someone switches from English to Sinhala),
    // since that alone doesn't publish/unpublish any track.
    updateOnlyOn: [RoomEvent.ParticipantAttributesChanged],
  })

  const visible = micTracks.filter((trackRef) => {
    // Never play a participant's own mic back to themselves.
    if (trackRef.participant.isLocal) return false

    const identity = trackRef.participant.identity
    if (identity.startsWith(TRANSLATOR_IDENTITY_PREFIX)) {
      return identity === `${TRANSLATOR_IDENTITY_PREFIX}-${preferredLanguage}`
    }
    const speakerLanguage = trackRef.participant.attributes?.language || 'en'
    return speakerLanguage === preferredLanguage
  })

  return (
    <div style={{ display: 'none' }}>
      {visible.map((trackRef) => (
        <AudioTrack key={trackRef.publication.trackSid} trackRef={trackRef} />
      ))}
    </div>
  )
}
