import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { listInbox, markMessageRead, sendMessage } from '../api/tasking'
import { listStaffLite } from '../api/staffDirectory'

export default function StaffInboxPage() {
  const { staff } = useAuth()
  const [messages, setMessages] = useState([])
  const [staffOptions, setStaffOptions] = useState([])
  const [showCompose, setShowCompose] = useState(false)
  const [form, setForm] = useState({ recipient_staff_id: '', subject: '', body: '' })
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)

  async function refresh() {
    setMessages(await listInbox())
  }

  useEffect(() => {
    refresh()
    listStaffLite().then((all) => setStaffOptions(all.filter((s) => s.id !== staff?.id)))
  }, [])

  async function handleOpen(message) {
    if (!message.read_at) {
      await markMessageRead(message.id)
      refresh()
    }
  }

  async function handleSend(e) {
    e.preventDefault()
    setError('')
    setSending(true)
    try {
      await sendMessage(form)
      setForm({ recipient_staff_id: '', subject: '', body: '' })
      setShowCompose(false)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send message')
    } finally {
      setSending(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>Inbox</h1>
          <p style={{ color: 'var(--sub)' }}>Messages from the admin or other staff — including meeting invitations.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCompose(!showCompose)}>
          {showCompose ? 'Cancel' : '+ New message'}
        </button>
      </div>

      {showCompose && (
        <form onSubmit={handleSend} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8 }}>
          {error && <div className="badge badge-alert" style={{ display: 'block', padding: '8px 12px' }}>{error}</div>}
          <select
            required
            value={form.recipient_staff_id}
            onChange={(e) => setForm({ ...form, recipient_staff_id: e.target.value })}
            style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8 }}
          >
            <option value="">— send to —</option>
            {staffOptions.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
          </select>
          <input
            placeholder="Subject (optional)"
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
            style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8 }}
          />
          <textarea
            required
            placeholder="Message"
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8, minHeight: 70, fontFamily: 'inherit' }}
          />
          <button type="submit" className="btn btn-primary" disabled={sending}>{sending ? 'Sending…' : 'Send'}</button>
        </form>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {messages.map((m) => (
          <div
            key={m.id}
            className="card card-clickable"
            style={{ padding: 14 }}
            onClick={() => handleOpen(m)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                {!m.read_at && <span className="badge badge-agent" style={{ marginRight: 6 }}>new</span>}
                {m.related_meeting_id && <span className="badge badge-id" style={{ marginRight: 6 }}>meeting</span>}
                <strong>{m.subject || '(no subject)'}</strong>
                <div style={{ fontSize: 13, color: 'var(--sub)', marginTop: 4 }}>{m.body}</div>
              </div>
              <span style={{ fontSize: 12, color: 'var(--sub)', whiteSpace: 'nowrap' }}>{new Date(m.created_at).toLocaleString()}</span>
            </div>
          </div>
        ))}
        {messages.length === 0 && <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>Nothing in your inbox yet.</div>}
      </div>
    </div>
  )
}
