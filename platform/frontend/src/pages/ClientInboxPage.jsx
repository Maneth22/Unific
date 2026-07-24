import React, { useEffect, useState } from 'react'
import { useClientAuth } from '../context/ClientAuthContext'
import { listMyInbox, markMyMessageRead, sendNotice } from '../api/clientProfiles'

export default function ClientInboxPage() {
  const { isOwner } = useClientAuth()
  const [messages, setMessages] = useState([])
  const [showCompose, setShowCompose] = useState(false)
  const [form, setForm] = useState({ subject: '', body: '' })
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)

  async function refresh() {
    if (isOwner) setMessages(await listMyInbox())
  }

  useEffect(() => { refresh() }, [isOwner])

  async function handleOpen(message) {
    if (!message.read_at) {
      await markMyMessageRead(message.id)
      refresh()
    }
  }

  async function handleSend(e) {
    e.preventDefault()
    setError('')
    setSending(true)
    try {
      await sendNotice(form)
      setForm({ subject: '', body: '' })
      setShowCompose(false)
      if (isOwner) await refresh()
      else setError('') // staff can send but won't see the reply thread — owner-only inbox
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send notice')
    } finally {
      setSending(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>Notices &amp; Inbox</h1>
          <p style={{ color: 'var(--sub)' }}>Send a concern or question to the UNIFIC admin, and see their replies here.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCompose(!showCompose)}>
          {showCompose ? 'Cancel' : '+ New notice'}
        </button>
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      {showCompose && (
        <form onSubmit={handleSend} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8 }}>
          <input
            placeholder="Subject (optional)"
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
            style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8 }}
          />
          <textarea
            required
            placeholder="What's on your mind?"
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8, minHeight: 70, fontFamily: 'inherit' }}
          />
          <button type="submit" className="btn btn-primary" disabled={sending}>{sending ? 'Sending…' : 'Send to admin'}</button>
        </form>
      )}

      {!isOwner ? (
        <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>
          You can send a notice above — replies from the admin go to your organization's owner inbox.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {messages.map((m) => (
            <div key={m.id} className="card card-clickable" style={{ padding: 14 }} onClick={() => handleOpen(m)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  {!m.read_at && <span className="badge badge-agent" style={{ marginRight: 6 }}>new</span>}
                  <strong>{m.subject || '(no subject)'}</strong>
                  <div style={{ fontSize: 13, color: 'var(--sub)', marginTop: 4 }}>{m.body}</div>
                </div>
                <span style={{ fontSize: 12, color: 'var(--sub)', whiteSpace: 'nowrap' }}>{new Date(m.created_at).toLocaleString()}</span>
              </div>
            </div>
          ))}
          {messages.length === 0 && <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>Nothing yet — notices you send and replies from admin will show up here.</div>}
        </div>
      )}
    </div>
  )
}
