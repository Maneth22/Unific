import React, { useEffect, useState } from 'react'
import { useRoomContext } from '@livekit/components-react'
import { TRANSLATION_STATUS_DETAIL_TOPIC, TRANSLATION_STATUS_TOPIC } from './callConstants'

// Status/retry notification ONLY — the Translator's actual visible
// PRESENCE as "an active participant" now comes from a real grid tile
// (see CallLayout.jsx: the bot is no longer filtered out of useTracks(),
// so it gets the same camera-off placeholder tile, name, and native
// `data-lk-speaking` highlight any other participant would, with zero
// extra code here). This component only ever renders something when
// there's actually a problem to report — surfacing live degradation from
// the backend's lk.translation_status / lk.translation_status.detail
// topics (see app/meeting_room/live_agents/status.py). A degraded notice
// is only ever shown once a failure has actually persisted for a while
// (the backend self-heals transient blips silently, see
// dubbed_audio.py's LanguageAudioPipeline._supervise) — and clears
// itself automatically (`payload.recovered`) the moment the backend
// reconnects, no manual dismiss/retry needed for that case.
//
// The raw failure detail is only ever subscribed to when
// viewerRole==='staff' — a guest/host client never holds that text in
// state at all, not just hidden from view. Retry is offered to staff and
// the meeting's host/client (viewerRole !=='guest'); a guest sees the
// same generic message with no button and no dismiss — degradation is
// meaningful to them, but retrying restarts the shared pipeline for
// everyone, so it stays a staff/host action.
export default function TranslatorParticipant({ active, viewerRole = 'guest', onRetry }) {
  const room = useRoomContext()
  const [status, setStatus] = useState(null) // { scope, subject, message } | null
  const [detail, setDetail] = useState(null) // staff-only raw exception text
  const [dismissed, setDismissed] = useState(false)
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    if (!room) return

    const onStatus = async (reader) => {
      let payload
      try {
        payload = JSON.parse(await reader.readAll())
      } catch {
        return
      }
      if (payload.recovered) {
        // Backend only ever sends this after a failure actually crossed
        // its own report threshold and surfaced here — clear the bubble
        // the same way a manual dismiss/retry would, no click needed.
        setStatus(null)
        setDetail(null)
        setDismissed(false)
        return
      }
      setStatus(payload)
      setDismissed(false)
    }
    room.registerTextStreamHandler(TRANSLATION_STATUS_TOPIC, onStatus)

    let onDetail
    if (viewerRole === 'staff') {
      onDetail = async (reader) => {
        let payload
        try {
          payload = JSON.parse(await reader.readAll())
        } catch {
          return
        }
        setDetail(payload.detail || null)
      }
      room.registerTextStreamHandler(TRANSLATION_STATUS_DETAIL_TOPIC, onDetail)
    }

    return () => {
      room.unregisterTextStreamHandler(TRANSLATION_STATUS_TOPIC)
      if (onDetail) room.unregisterTextStreamHandler(TRANSLATION_STATUS_DETAIL_TOPIC)
    }
  }, [room, viewerRole])

  const canRetry = viewerRole !== 'guest'
  const showDegraded = active && !!status && !dismissed

  async function handleRetry() {
    const prevStatus = status
    const prevDetail = detail
    setStatus(null)
    setDetail(null)
    setRetrying(true)
    try {
      await onRetry?.()
    } catch {
      // Restart failed to even submit (network/scope error) — put the
      // notice back rather than silently claim it's fine now. A genuine
      // retry failure the backend accepted still comes back through the
      // status topic on its own.
      setStatus(prevStatus)
      setDetail(prevDetail)
    } finally {
      setRetrying(false)
    }
  }

  if (!showDegraded) return null

  return (
    <div className="cq-translation-indicator" role="status">
      <div className={`cq-device-bubble cq-translator-bubble ${canRetry ? '' : 'cq-device-bubble-readonly'}`} role="alert">
        <p>
          {status.message}
          {viewerRole === 'staff' && detail ? ` (${detail})` : ''}
        </p>
        {canRetry && (
          <div className="cq-device-bubble-actions">
            <button type="button" className="btn cq-device-bubble-retry" disabled={retrying} onClick={handleRetry}>
              {retrying ? 'Retrying…' : 'Retry'}
            </button>
            <button type="button" className="cq-device-bubble-dismiss" aria-label="Dismiss" onClick={() => setDismissed(true)}>
              ×
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
