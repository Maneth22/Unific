import React, { useEffect, useRef, useState } from 'react'
import { RoomEvent, Track } from 'livekit-client'
import {
  CarouselLayout,
  Chat,
  FocusLayout,
  FocusLayoutContainer,
  GridLayout,
  LayoutContextProvider,
  ParticipantTile,
  isTrackReference,
  useCreateLayoutContext,
  useParticipants,
  usePinnedTracks,
  useSpeakingParticipants,
  useTracks,
} from '@livekit/components-react'
import ParticipantTileBody from './ParticipantTileBody'
import CallControlBar from './CallControlBar'
import SelectiveAudioRenderer from './SelectiveAudioRenderer'
import TranslationIndicator from './TranslationIndicator'
import { SPEAKER_FOCUS_PARTICIPANT_THRESHOLD, TRANSLATOR_IDENTITY_PREFIX, sameTrackRef } from './callConstants'

// Replaces LiveKit's <VideoConference/> prefab with the same building blocks
// it uses internally (useTracks/GridLayout/FocusLayoutContainer/
// ParticipantTile), so we keep the library's well-tested per-track
// subscription and pin/focus machinery while controlling the visuals
// (ParticipantTileBody) and adding a second auto-focus source: the active
// speaker, once the call gets crowded (see the second effect below).
export default function CallLayout({ deviceErrors }) {
  const [widgetState, setWidgetState] = useState({ showChat: false, unreadMessages: 0 })
  const [preferredLanguage, setPreferredLanguage] = useState('en')
  const lastAutoFocusedScreenShareTrack = useRef(null)
  const lastAutoFocusedSpeakerIdentity = useRef(null)

  // Four separate translator bots (one per language, see
  // live_translation.py) each join the room as their own participant, but
  // they're an implementation detail, not people on the call — without
  // filtering, each would get its own camera-off placeholder tile here
  // (withPlaceholder: true gives every camera-less participant one),
  // cluttering the grid with 4 silent "XX Translator" tiles. Excluded here
  // at the source so every derived list (screen share, carousel, the
  // crowd-threshold count) stays clean automatically; TranslationIndicator
  // below shows one single "translation active" signal instead.
  const tracks = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true },
      { source: Track.Source.ScreenShare, withPlaceholder: false },
    ],
    { updateOnlyOn: [RoomEvent.ActiveSpeakersChanged], onlySubscribed: false },
  ).filter((track) => !track.participant.identity.startsWith(TRANSLATOR_IDENTITY_PREFIX))

  const layoutContext = useCreateLayoutContext()
  const speakingParticipants = useSpeakingParticipants()
  const translationActive = useParticipants().some((p) => p.identity.startsWith(TRANSLATOR_IDENTITY_PREFIX))

  const screenShareTracks = tracks
    .filter(isTrackReference)
    .filter((track) => track.publication.source === Track.Source.ScreenShare)

  const focusTrack = usePinnedTracks(layoutContext)?.[0]
  const carouselTracks = tracks.filter((track) => !sameTrackRef(track, focusTrack))

  // Effect 1 (highest priority) — auto-pin the first screen-share track the
  // instant one appears, auto-clear when it disappears. Copied verbatim from
  // @livekit/components-react's VideoConference.tsx; always wins over the
  // speaker-focus effect below.
  useEffect(() => {
    if (
      screenShareTracks.some((track) => track.publication.isSubscribed) &&
      lastAutoFocusedScreenShareTrack.current === null
    ) {
      layoutContext.pin.dispatch?.({ msg: 'set_pin', trackReference: screenShareTracks[0] })
      lastAutoFocusedScreenShareTrack.current = screenShareTracks[0]
    } else if (
      lastAutoFocusedScreenShareTrack.current &&
      !screenShareTracks.some(
        (track) => track.publication.trackSid === lastAutoFocusedScreenShareTrack.current?.publication?.trackSid,
      )
    ) {
      layoutContext.pin.dispatch?.({ msg: 'clear_pin' })
      lastAutoFocusedScreenShareTrack.current = null
    }
    if (focusTrack && !isTrackReference(focusTrack)) {
      const updatedFocusTrack = tracks.find(
        (tr) => tr.participant.identity === focusTrack.participant.identity && tr.source === focusTrack.source,
      )
      if (updatedFocusTrack !== focusTrack && isTrackReference(updatedFocusTrack)) {
        layoutContext.pin.dispatch?.({ msg: 'set_pin', trackReference: updatedFocusTrack })
      }
    }
  }, [
    screenShareTracks.map((ref) => `${ref.publication.trackSid}_${ref.publication.isSubscribed}`).join(),
    focusTrack?.publication?.trackSid,
    tracks,
  ])

  // Effect 2 (lower priority) — once the grid gets crowded, auto-pin the
  // active/dominant speaker instead of leaving everyone in an
  // ever-shrinking grid. Only ever touches a pin it set itself (tracked via
  // lastAutoFocusedSpeakerIdentity), so a manual double-click pin (the
  // tile's built-in <FocusToggle/>) is never overridden, and screen share
  // (effect 1) always takes precedence.
  useEffect(() => {
    const anyScreenShareActive = screenShareTracks.some((t) => t.publication.isSubscribed)
    if (anyScreenShareActive) return

    const cameraTracks = tracks.filter((t) => t.source === Track.Source.Camera)
    const participantCount = new Set(cameraTracks.map((t) => t.participant.identity)).size

    if (participantCount > SPEAKER_FOCUS_PARTICIPANT_THRESHOLD) {
      const isPinnedByUsOrUnpinned =
        !focusTrack || focusTrack.participant.identity === lastAutoFocusedSpeakerIdentity.current
      if (!isPinnedByUsOrUnpinned) return // a manual pin is active — leave it alone

      const dominant =
        speakingParticipants[0] ||
        cameraTracks.find((t) => t.participant.identity === lastAutoFocusedSpeakerIdentity.current)?.participant ||
        cameraTracks[0]?.participant

      if (dominant && focusTrack?.participant.identity !== dominant.identity) {
        const dominantTrack = cameraTracks.find((t) => t.participant.identity === dominant.identity)
        if (dominantTrack) {
          layoutContext.pin.dispatch?.({ msg: 'set_pin', trackReference: dominantTrack })
          lastAutoFocusedSpeakerIdentity.current = dominant.identity
        }
      }
    } else if (
      lastAutoFocusedSpeakerIdentity.current &&
      focusTrack?.participant.identity === lastAutoFocusedSpeakerIdentity.current
    ) {
      // Crowd thinned back out and the current pin is still our own — clear
      // back to grid view. A manual pin below threshold is left untouched.
      layoutContext.pin.dispatch?.({ msg: 'clear_pin' })
      lastAutoFocusedSpeakerIdentity.current = null
    }
  }, [
    tracks,
    speakingParticipants.map((p) => p.identity).join(),
    focusTrack?.participant?.identity,
    screenShareTracks.map((t) => `${t.publication.trackSid}_${t.publication.isSubscribed}`).join(),
  ])

  return (
    <div className="lk-video-conference cq-call-shell">
      <TranslationIndicator active={translationActive} />
      <LayoutContextProvider value={layoutContext} onWidgetChange={setWidgetState}>
        <div className="lk-video-conference-inner">
          {!focusTrack ? (
            <div className="lk-grid-layout-wrapper">
              <GridLayout tracks={tracks}>
                <ParticipantTile>
                  <ParticipantTileBody />
                </ParticipantTile>
              </GridLayout>
            </div>
          ) : (
            <div className="lk-focus-layout-wrapper">
              <FocusLayoutContainer>
                <CarouselLayout tracks={carouselTracks}>
                  <ParticipantTile>
                    <ParticipantTileBody />
                  </ParticipantTile>
                </CarouselLayout>
                <FocusLayout trackRef={focusTrack}>
                  <ParticipantTileBody />
                </FocusLayout>
              </FocusLayoutContainer>
            </div>
          )}
          <CallControlBar
            deviceErrors={deviceErrors}
            preferredLanguage={preferredLanguage}
            setPreferredLanguage={setPreferredLanguage}
          />
        </div>
        <Chat style={{ display: widgetState.showChat ? 'grid' : 'none' }} />
      </LayoutContextProvider>
      <SelectiveAudioRenderer preferredLanguage={preferredLanguage} />
    </div>
  )
}
