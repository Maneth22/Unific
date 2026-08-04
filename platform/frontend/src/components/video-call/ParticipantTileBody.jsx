import React from 'react'
import { Track } from 'livekit-client'
import {
  ConnectionQualityIndicator,
  LockLockedIcon,
  ParticipantName,
  ScreenShareIcon,
  TrackMutedIndicator,
  VideoTrack,
  isTrackReference,
  useEnsureTrackRef,
  useIsEncrypted,
  useIsMuted,
} from '@livekit/components-react'

function initials(name) {
  return (name || '?')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || '?'
}

// Custom body for <ParticipantTile>, passed as its `children`. The library
// still handles subscription lifecycle, click-to-pin (<FocusToggle>), and
// context wiring around whatever children we give it — this only replaces
// what's drawn inside the tile: a real video element, or (when off/not yet
// published/muted) a themed dark placeholder square instead of a blank tile
// or the library's generic silhouette icon.
//
// Deliberate guardrail against the investigated "can't see others' video"
// bug: this component only ever reads the ONE track reference it's handed
// via context (useEnsureTrackRef), scoped to a single participant+source. It
// never reaches into any other participant's state or any shared/global
// camera flag — every tile in the grid renders fully independently, exactly
// like the library's own per-track architecture already guarantees.
export default function ParticipantTileBody() {
  const trackRef = useEnsureTrackRef()
  const isEncrypted = useIsEncrypted(trackRef.participant)
  const isVideoMuted = useIsMuted(trackRef)
  const isScreenShare = trackRef.source === Track.Source.ScreenShare

  if (isScreenShare) {
    // Screen share has no "muted"/placeholder concept — always render the
    // video track, matching the library's own default tile behavior.
    return (
      <>
        <VideoTrack trackRef={trackRef} className="cq-tile-video" />
        <div className="lk-participant-metadata cq-tile-meta">
          <div className="lk-participant-metadata-item">
            <ScreenShareIcon style={{ marginRight: '0.25rem' }} />
            <ParticipantName>&apos;s screen</ParticipantName>
          </div>
        </div>
      </>
    )
  }

  const showVideo = !isVideoMuted && isTrackReference(trackRef)

  return (
    <>
      {showVideo ? (
        <VideoTrack trackRef={trackRef} className="cq-tile-video" />
      ) : (
        <div className="cq-tile-placeholder">
          <div className="cq-tile-avatar">{initials(trackRef.participant.name || trackRef.participant.identity)}</div>
        </div>
      )}
      <div className="lk-participant-metadata cq-tile-meta">
        <div className="lk-participant-metadata-item">
          {isEncrypted && <LockLockedIcon style={{ marginRight: '0.25rem' }} />}
          <TrackMutedIndicator
            trackRef={{ participant: trackRef.participant, source: Track.Source.Microphone }}
            show="muted"
          />
          <ParticipantName />
        </div>
        <ConnectionQualityIndicator className="lk-participant-metadata-item" />
      </div>
    </>
  )
}
