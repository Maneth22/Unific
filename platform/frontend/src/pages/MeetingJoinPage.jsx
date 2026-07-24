import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getJoinInfo, submitPublicJoin } from '../api/publicMeetingRoom'
import VideoCallRoom from '../components/VideoCallRoom'

// Fully public — no auth wrapper, no nav chrome. A WhatsApp-only community
// member (or anyone else holding a valid invite link) reaches this page
// straight from the link a staff member shared — no login required, the
// token itself is the join credential. Mirrors MemberRegistrationPage.jsx.
export default function MeetingJoinPage() {
  const { token } = useParams()
  const [info, setInfo] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [call, setCall] = useState(null)
  const [joining, setJoining] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getJoinInfo(token)
      .then(setInfo)
      .catch(() => setLoadError('This meeting link is invalid or has expired.'))
  }, [token])

  async function handleJoin() {
    setError('')
    setJoining(true)
    try {
      const join = await submitPublicJoin(token)
      setCall(join)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not join the meeting')
    } finally {
      setJoining(false)
    }
  }

  if (call) {
    return <VideoCallRoom serverUrl={call.livekit_url} token={call.token} onDisconnected={() => setCall(null)} />
  }

  if (loadError) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ width: 340, padding: 28, textAlign: 'center', color: 'var(--sub)' }}>{loadError}</div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="card" style={{ width: 380, padding: 28, textAlign: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>
          {info ? `Hi, ${info.participant_name}` : 'Loading…'}
        </div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: 20 }}>
          {info ? `Meeting scheduled for ${new Date(info.scheduled_at).toLocaleString()} — ${info.status}.` : ''}
        </div>

        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>{error}</div>}

        <button
          className="btn btn-primary"
          style={{ width: '100%' }}
          disabled={joining || !info || info.status === 'completed' || info.status === 'cancelled'}
          onClick={handleJoin}
        >
          {joining ? 'Joining…' : 'Join meeting'}
        </button>
      </div>
    </div>
  )
}
