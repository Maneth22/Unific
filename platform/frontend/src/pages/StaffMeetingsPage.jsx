import React, { useEffect, useRef, useState } from 'react'
import { getMyStaffMeetingChat, joinMeeting, listMyMeetings, retryMeetingTranslation } from '../api/meetingRoom'
import VideoCallRoom from '../components/VideoCallRoom'

const STATUS_BADGE = {
  scheduled: 'badge-pending',
  live: 'badge-agent',
  completed: 'badge-room',
  cancelled: 'badge-alert',
}

// The regular-staff counterpart to the admin's Meeting Scheduler — no
// create/end/delete here, just the meetings this staff account was invited
// to (or has already joined) and a way to join the call.
export default function StaffMeetingsPage() {
  const [meetings, setMeetings] = useState([])
  const [error, setError] = useState('')
  const [pendingId, setPendingId] = useState('')
  const [call, setCall] = useState(null)
  const callActive = useRef(false)

  async function refresh() {
    setMeetings(await listMyMeetings())
  }

  useEffect(() => { refresh() }, [])

  useEffect(() => {
    callActive.current = !!call
    const id = setInterval(() => { if (!callActive.current) refresh() }, 5000)
    return () => clearInterval(id)
  }, [call])

  async function handleJoin(meetingId) {
    setError('')
    setPendingId(meetingId)
    try {
      const join = await joinMeeting(meetingId)
      setCall(join)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not join meeting')
    } finally {
      setPendingId('')
    }
  }

  if (call) {
    return (
      <div>
        <button className="btn" style={{ marginBottom: 12 }} onClick={() => setCall(null)}>&larr; Leave call</button>
        <VideoCallRoom
          serverUrl={call.livekit_url}
          token={call.token}
          languages={call.languages}
          openInviteUrl={call.open_invite_url}
          onDisconnected={() => setCall(null)}
          fetchChatHistory={() => getMyStaffMeetingChat(call.meeting_id)}
          viewerRole="staff"
          onRetryTranslation={() => retryMeetingTranslation(call.meeting_id)}
        />
      </div>
    )
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Meetings</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>Meetings you've been invited to.</p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {meetings.map((m) => (
          <div key={m.id} className="card" style={{ padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span className={`badge ${STATUS_BADGE[m.status] || 'badge-room'} ${m.status === 'live' ? 'badge-pulse' : ''}`}>
                {m.status}
              </span>{' '}
              <span style={{ fontSize: 13 }}>{new Date(m.scheduled_at).toLocaleString()}</span>
              {m.notes && <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 4 }}>{m.notes}</div>}
            </div>
            {(m.status === 'scheduled' || m.status === 'live') && (
              <button className="btn btn-primary" disabled={!!pendingId} onClick={() => handleJoin(m.id)}>
                {pendingId === m.id ? 'Joining…' : 'Join'}
              </button>
            )}
            {(m.status === 'completed' || m.status === 'cancelled') && (
              <span style={{ fontSize: 12, color: 'var(--sub)' }}>Ended</span>
            )}
          </div>
        ))}
        {meetings.length === 0 && <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>No meeting invitations yet.</div>}
      </div>
    </div>
  )
}
