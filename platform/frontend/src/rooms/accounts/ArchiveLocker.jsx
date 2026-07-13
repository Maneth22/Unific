import React, { useEffect, useState } from 'react'
import { createArchiveItem, listArchiveShelf } from '../../api/accounts'

const SHELVES = [
  { key: 'operational_library', label: 'Operational Library', badge: 'badge-agent' },
  { key: 'transfer', label: 'Transfer (outgoing)', badge: 'badge-pending' },
  { key: 'receiving', label: 'Receiving (incoming)', badge: 'badge-id' },
]

export default function ArchiveLocker() {
  const [shelf, setShelf] = useState('operational_library')
  const [items, setItems] = useState([])
  const [form, setForm] = useState({ title: '', description: '', approved_for_auto_reply: false })
  const [error, setError] = useState('')

  async function refresh() {
    setItems(await listArchiveShelf(shelf))
  }

  useEffect(() => { refresh() }, [shelf])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createArchiveItem(form)
      setForm({ title: '', description: '', approved_for_auto_reply: false })
      if (shelf === 'operational_library') refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add item')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Three shelves: the room's working truth (Operational Library), what's approved to leave
        (Transfer), and what's arrived pending review (Receiving) — nothing is ever auto-accepted.
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {SHELVES.map((s) => (
          <button
            key={s.key}
            className="btn"
            style={{ background: shelf === s.key ? 'var(--slate)' : 'var(--surface)', color: shelf === s.key ? 'white' : 'var(--ink)' }}
            onClick={() => setShelf(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      {shelf === 'operational_library' && (
        <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8 }}>
          <input placeholder="Title" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={inputStyle} />
          <input placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={inputStyle} />
          <button type="submit" className="btn btn-primary">Add to Operational Library</button>
        </form>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {items.map((item) => (
          <div key={item.id} className="card" style={{ padding: 12 }}>
            <span className={`badge ${SHELVES.find((s) => s.key === shelf)?.badge}`}>{item.status}</span>{' '}
            <strong>{item.title}</strong>
            {item.description && <div style={{ fontSize: 12, color: 'var(--sub)' }}>{item.description}</div>}
          </div>
        ))}
        {items.length === 0 && <div style={{ color: 'var(--sub)' }}>Nothing on this shelf.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
