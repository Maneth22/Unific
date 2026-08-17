import React, { useEffect, useRef, useState } from 'react'
import { useParticipants, useRoomContext } from '@livekit/components-react'
import { CAPTION_TEXT_TOPIC, TRANSCRIBED_TRACK_ID_ATTR } from './callConstants'

// A Zoom/Meet-style single-line caption bar at the bottom of the call.
// Server-targeted: the backend's live_agents.captions dispatcher sends
// each translated segment via LiveKit's `destination_identities`, so
// every message THIS client ever receives on CAPTION_TEXT_TOPIC is
// already in this listener's own caption_language — no client-side
// sender/language filtering needed at all (unlike the old design, which
// broadcast every language to everyone and let each client self-filter
// by sender identity). Only the single most-recent line is kept, replaced
// wholesale on each new one — no scrollback, matching the backend's
// "flush the whole turn in one message" design (captions are segmented
// on VAD end-of-turn, not streamed word by word).
export default function CaptionBar({ captionLanguage }) {
  const room = useRoomContext()
  const participants = useParticipants()
  const [caption, setCaption] = useState(null) // { speakerName, text } | null

  // Kept in a ref (not a handler dependency) so the text-stream handler
  // below always sees the current participant list without needing to be
  // torn down and re-registered on every join/leave — an unregister/
  // register gap could otherwise miss a caption arriving mid-swap.
  const participantsRef = useRef(participants)
  useEffect(() => {
    participantsRef.current = participants
  }, [participants])

  // Clear the displayed line the moment the viewer switches languages —
  // the line on screen was in the old language and would otherwise sit
  // there stale until the next segment arrives in the new one.
  useEffect(() => {
    setCaption(null)
  }, [captionLanguage])

  useEffect(() => {
    if (!room) return

    const handler = async (reader, _participantInfo) => {
      const text = await reader.readAll()
      if (!text) return
      const trackId = reader.info.attributes?.[TRANSCRIBED_TRACK_ID_ATTR]
      const speaker = trackId
        ? participantsRef.current.find((p) => p.trackPublications.has(trackId))
        : undefined
      setCaption({ speakerName: speaker?.name || speaker?.identity || 'Someone', text })
    }

    room.registerTextStreamHandler(CAPTION_TEXT_TOPIC, handler)
    return () => room.unregisterTextStreamHandler(CAPTION_TEXT_TOPIC)
  }, [room])

  if (!caption) return null

  return (
    <div className="cq-caption-bar" role="status">
      <strong>{caption.speakerName}:</strong> {caption.text}
    </div>
  )
}
