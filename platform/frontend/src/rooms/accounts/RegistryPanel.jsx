import React, { useEffect, useState } from 'react'
import { createRegistryEntry, listRegistry, revealSecret } from '../../api/accounts'

const CATEGORIES = ['ai_platform', 'comms_platform', 'payment', 'hosting', 'domain', 'government', 'banking', 'tool', 'other']

export default function RegistryPanel() {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ name: '', category: 'ai_platform', provider: '', purpose: '', owner: '', secret: '' })
  const [revealed, setRevealed] = useState({})
  const [error, setError] = useState('')

  async function refresh() {
    setLoading(true)
    try {
      setEntries(await listRegistry())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createRegistryEntry({ ...form, secret: form.secret || null })
      setForm({ name: '', category: 'ai_platform', provider: '', purpose: '', owner: '', secret: '' })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create registry entry')
    }
  }

  async function handleReveal(id) {
    if (revealed[id]) {
      setRevealed((r) => { const next = { ...r }; delete next[id]; return next })
      return
    }
    try {
      const { secret } = await revealSecret(id)
      setRevealed((r) => ({ ...r, [id]: secret }))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not reveal secret — you may need admin-level room access')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Every account UNIFIC uses. Credentials are encrypted at rest and only ever decrypted
        through the reveal action below, which requires admin-level room access and is always
        audit-logged.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        <input placeholder="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={inputStyle} />
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} style={inputStyle}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input placeholder="Provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} style={inputStyle} />
        <input placeholder="Owner" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} style={inputStyle} />
        <input placeholder="Purpose" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} style={{ ...inputStyle, gridColumn: '1 / -1' }} />
        <input placeholder="Secret (optional — encrypted at rest)" type="password" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} style={{ ...inputStyle, gridColumn: '1 / -1' }} />
        <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Add account</button>
      </form>

      {loading ? <div>Loading…</div> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {entries.map((entry) => (
            <div key={entry.id} className="card" style={{ padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span className="badge badge-account">{entry.category}</span>{' '}
                <strong>{entry.name}</strong>
                <div style={{ fontSize: 12, color: 'var(--sub)' }}>{entry.provider} · owner: {entry.owner || '—'}</div>
                {revealed[entry.id] && (
                  <div style={{ fontSize: 12, marginTop: 6, fontFamily: 'monospace', background: 'var(--neutral-bg)', padding: '4px 8px', borderRadius: 6 }}>
                    {revealed[entry.id]}
                  </div>
                )}
              </div>
              {entry.has_secret && (
                <button className="btn" onClick={() => handleReveal(entry.id)}>
                  {revealed[entry.id] ? 'Hide' : 'Reveal secret'}
                </button>
              )}
            </div>
          ))}
          {entries.length === 0 && <div style={{ color: 'var(--sub)' }}>No accounts registered yet.</div>}
        </div>
      )}
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
