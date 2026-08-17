import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getJoinInfo, getPublicMeetingChat, submitGuestJoin, submitPublicJoin } from '../api/publicMeetingRoom'
import VideoCallRoom from '../components/VideoCallRoom'

// Fully public — no auth wrapper, no nav chrome. Reached two ways: a
// personal (kind="personal") link a staff/client scheduler shared with a
// known participant (info.participant_name is already known — greets
// them by name, same as before), or the meeting's one shareable open
// (kind="open") link posted anywhere for a newcomer to use — that one
// doesn't know who's about to join, so it prompts for a name instead.
// Mirrors MemberRegistrationPage.jsx.
export default function MeetingJoinPage() {
  const { token } = useParams()
  const [info, setInfo] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [call, setCall] = useState(null)
  const [joining, setJoining] = useState(false)
  const [error, setError] = useState('')
  const [guestName, setGuestName] = useState('')

  useEffect(() => {
    getJoinInfo(token)
      .then(setInfo)
      .catch(() => setLoadError('This meeting link is invalid or has expired.'))
  }, [token])

  const isOpenLink = info?.kind === 'open'

  async function handleJoin(e) {
    e.preventDefault()
    setError('')
    setJoining(true)
    try {
      const join = isOpenLink ? await submitGuestJoin(token, guestName.trim()) : await submitPublicJoin(token)
      setCall(join)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not join the meeting')
    } finally {
      setJoining(false)
    }
  }

  if (call) {
    return (
      <VideoCallRoom
        serverUrl={call.livekit_url}
        token={call.token}
        languages={call.languages}
        openInviteUrl={call.open_invite_url}
        onDisconnected={() => setCall(null)}
        fetchChatHistory={() => getPublicMeetingChat(token)}
      />
    )
  }

  if (loadError) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ width: 340, padding: 28, textAlign: 'center', color: 'var(--sub)' }}>{loadError}</div>
      </div>
    )
  }

  const joinDisabled =
    joining || !info || info.status === 'completed' || info.status === 'cancelled' || (isOpenLink && !guestName.trim())

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="card" style={{ width: 380, padding: 28, textAlign: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>
          {!info ? 'Loading…' : isOpenLink ? "You're invited to join" : `Hi, ${info.participant_name}`}
        </div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: isOpenLink ? 12 : 20 }}>
          {info ? `Meeting scheduled for ${new Date(info.scheduled_at).toLocaleString()} — ${info.status}.` : ''}
        </div>
        {isOpenLink && (
          <div style={{ color: 'var(--sub)', fontSize: 12, marginBottom: 12 }}>
            Anyone with this link can join — enter your name to continue.
          </div>
        )}

        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>{error}</div>}

        <form onSubmit={handleJoin}>
          {isOpenLink && (
            <input
              autoFocus
              placeholder="Your name"
              value={guestName}
              onChange={(e) => setGuestName(e.target.value)}
              style={{ width: '100%', padding: 10, marginBottom: 12, border: '1px solid var(--line)', borderRadius: 8, boxSizing: 'border-box' }}
            />
          )}
          <button className="btn btn-primary" style={{ width: '100%' }} disabled={joinDisabled} type="submit">
            {joining ? 'Joining…' : 'Join meeting'}
          </button>
        </form>
      </div>
    </div>
  )
}
