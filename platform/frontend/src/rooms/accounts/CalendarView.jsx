import React, { useEffect, useState } from 'react'
import { createCalendarEvent, listCalendar } from '../../api/accounts'

export default function CalendarView() {
  const [events, setEvents] = useState([])
  const [form, setForm] = useState({ kind: 'renewal', title: '', due_at: '' })
  const [error, setError] = useState('')

  async function refresh() {
    setEvents(await listCalendar())
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createCalendarEvent({ ...form, due_at: new Date(form.due_at).toISOString() })
      setForm({ kind: 'renewal', title: '', due_at: '' })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add calendar event')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        The one master calendar — renewals, payments, deadlines, milestones. Every room reads a
        view of it; this is the Accounts Room's view.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        <input placeholder="Kind (e.g. renewal, payment)" required value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} style={inputStyle} />
        <input type="datetime-local" required value={form.due_at} onChange={(e) => setForm({ ...form, due_at: e.target.value })} style={inputStyle} />
        <input placeholder="Title" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ ...inputStyle, gridColumn: '1 / -1' }} />
        <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Add event</button>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {events.map((e) => (
          <div key={e.id} className="card" style={{ padding: 12, display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <span className="badge badge-room">{e.kind}</span> {e.title}
            </div>
            <span style={{ fontSize: 12, color: 'var(--sub)' }}>{new Date(e.due_at).toLocaleString()}</span>
          </div>
        ))}
        {events.length === 0 && <div style={{ color: 'var(--sub)' }}>No upcoming events.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
