import React, { useEffect, useState } from 'react'
import { createWhatsAppLink, listWhatsAppLinks } from '../../api/meetingRoom'

export default function WhatsAppLinks() {
  const [links, setLinks] = useState([])
  const [form, setForm] = useState({ phone_number: '', identity_id: '' })
  const [error, setError] = useState('')

  async function refresh() {
    setLinks(await listWhatsAppLinks())
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createWhatsAppLink(form.phone_number, form.identity_id)
      setForm({ phone_number: '', identity_id: '' })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not link phone number')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Phone number to identity mapping. A "group" is this list plus 1:1 conversations — the
        WhatsApp Cloud API has no native groups.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'flex', gap: 8 }}>
        <input placeholder="Phone number (+91...)" required value={form.phone_number} onChange={(e) => setForm({ ...form, phone_number: e.target.value })} style={inputStyle} />
        <input placeholder="Identity ID" required value={form.identity_id} onChange={(e) => setForm({ ...form, identity_id: e.target.value })} style={inputStyle} />
        <button type="submit" className="btn btn-primary">Link</button>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {links.map((l) => (
          <div key={l.id} className="card" style={{ padding: 12, fontSize: 13 }}>
            <strong>{l.phone_number}</strong> <span style={{ color: 'var(--sub)' }}>→ {l.identity_id}</span>
          </div>
        ))}
        {links.length === 0 && <div style={{ color: 'var(--sub)' }}>No numbers linked yet.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8, flex: 1 }
