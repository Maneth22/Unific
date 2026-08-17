import React from 'react'
import { RoomEvent, Track } from 'livekit-client'
import { AudioTrack, useTracks } from '@livekit/components-react'
import { AUDIO_MODE_DUBBED_AUDIO, DUBBED_TRACK_NAME_PREFIX, LIVE_AGENTS_BOT_IDENTITY } from './callConstants'

// Replaces <RoomAudioRenderer/>, which plays every remote participant's
// audio track with no per-track control (confirmed: its only props are
// room-wide `volume`/`muted`).
//
// `audio_mode=captions_only` (the default): every participant's original
// mic plays normally, exactly like an ordinary call — captions
// (CaptionBar.jsx) are the only translation surface, no audio routing
// decision needed here at all.
//
// `audio_mode=dubbed_audio`: mute a remote speaker's original mic
// whenever their `spoken_language` differs from this listener's
// `captionLanguage`, and instead play the ONE shared
// `translated-<captionLanguage>` track — published once per active
// target language (never per speaker, never per listener) from the
// backend's single `live_agents` bot identity, distinguished by *track
// name*, not by a per-language participant identity like the old design.
export default function SelectiveAudioRenderer({ captionLanguage, audioMode }) {
  const micTracks = useTracks([Track.Source.Microphone], {
    onlySubscribed: true,
    // useTracks already re-renders on track subscribe/unsubscribe by
    // default; this adds a re-render when a speaker's declared
    // spoken_language changes mid-call, since that alone doesn't
    // publish/unpublish any track.
    updateOnlyOn: [RoomEvent.ParticipantAttributesChanged],
  })

  const dubbing = audioMode === AUDIO_MODE_DUBBED_AUDIO

  const visible = micTracks.filter((trackRef) => {
    // Never play a participant's own mic back to themselves.
    if (trackRef.participant.isLocal) return false

    if (trackRef.participant.identity === LIVE_AGENTS_BOT_IDENTITY) {
      // Only relevant in dubbed_audio mode, and only the one track
      // matching this listener's own caption language — the bot may have
      // several translated-<lang> tracks published at once (one per
      // language any dubbed_audio participant currently needs).
      return dubbing && trackRef.publication.trackName === `${DUBBED_TRACK_NAME_PREFIX}${captionLanguage}`
    }

    if (!dubbing) return true // captions_only — everyone's original mic plays normally

    const speakerLanguage = trackRef.participant.attributes?.spoken_language || 'en'
    // Mute this speaker's original mic unless they already speak my
    // caption language (dubbing someone into the language they're
    // already speaking would be pointless and would double up audio).
    return speakerLanguage === captionLanguage
  })

  return (
    <div style={{ display: 'none' }}>
      {visible.map((trackRef) => (
        <AudioTrack key={trackRef.publication.trackSid} trackRef={trackRef} />
      ))}
    </div>
  )
}
