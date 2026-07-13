import React, { useEffect, useState } from 'react'
import { createMeeting, listMeetings } from '../../api/meetingRoom'

export default function MeetingScheduler() {
  const [meetings, setMeetings] = useState([])
  const [form, setForm] = useState({ host_identity_id: '', scheduled_at: '', translate_live: true, notes: '' })
  const [error, setError] = useState('')

  async function refresh() {
    setMeetings(await listMeetings())
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createMeeting({ ...form, scheduled_at: new Date(form.scheduled_at).toISOString() })
      setForm({ host_identity_id: '', scheduled_at: '', translate_live: true, notes: '' })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not schedule meeting')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        The weekly meeting — a link is sent to the list; the host's words are translated live.
        Scheduling here also submits timing to the one master calendar in the Accounts Room.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        <input placeholder="Host identity ID (Group)" required value={form.host_identity_id} onChange={(e) => setForm({ ...form, host_identity_id: e.target.value })} style={inputStyle} />
        <input type="datetime-local" required value={form.scheduled_at} onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })} style={inputStyle} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={form.translate_live} onChange={(e) => setForm({ ...form, translate_live: e.target.checked })} />
          Translate live
        </label>
        <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} style={inputStyle} />
        <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Schedule</button>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {meetings.map((m) => (
          <div key={m.id} className="card" style={{ padding: 12, display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <span className="badge badge-room">{m.status}</span> {m.host_identity_id.slice(0, 8)}…
              {m.notes && <div style={{ fontSize: 12, color: 'var(--sub)' }}>{m.notes}</div>}
            </div>
            <span style={{ fontSize: 12, color: 'var(--sub)' }}>{new Date(m.scheduled_at).toLocaleString()}</span>
          </div>
        ))}
        {meetings.length === 0 && <div style={{ color: 'var(--sub)' }}>No meetings scheduled.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
