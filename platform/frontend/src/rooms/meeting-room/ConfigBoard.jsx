import React, { useState } from 'react'
import { getConfigBoard, updateConfigBoard } from '../../api/meetingRoom'

export default function ConfigBoard() {
  const [identityId, setIdentityId] = useState('')
  const [config, setConfig] = useState(null)
  const [form, setForm] = useState({})
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function handleLoad(e) {
    e.preventDefault()
    setError(''); setMessage('')
    try {
      setConfig(await getConfigBoard(identityId))
      setForm({})
    } catch (err) {
      setError('Identity not found')
      setConfig(null)
    }
  }

  async function handleSave(e) {
    e.preventDefault()
    setError(''); setMessage('')
    const payload = {}
    for (const [k, v] of Object.entries(form)) if (v) payload[k] = v
    try {
      const updated = await updateConfigBoard(identityId, payload)
      setConfig(updated)
      setForm({})
      setMessage('Saved. Preserved through translation, per-ID.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Role, tone, complexity, character, and language for every reply — held per ID, and kept
        the same through translation. Backed by the same narrowing cascade as Profiles
        permissions (this is a Meeting Room view over that data, not a separate store).
      </p>

      <form onSubmit={handleLoad} className="card" style={{ padding: 14, marginBottom: 16, display: 'flex', gap: 8 }}>
        <input placeholder="Identity ID" required value={identityId} onChange={(e) => setIdentityId(e.target.value)} style={{ flex: 1, ...inputStyle }} />
        <button type="submit" className="btn">Load</button>
      </form>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{message}</div>}

      {config && (
        <form onSubmit={handleSave} className="card" style={{ padding: 16, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
          {['role', 'tone', 'complexity', 'character', 'language'].map((field) => (
            <div key={field}>
              <div style={{ fontSize: 11, color: 'var(--sub)', textTransform: 'uppercase', marginBottom: 3 }}>{field}</div>
              <input
                defaultValue={config[field]}
                onChange={(e) => setForm({ ...form, [field]: e.target.value })}
                style={inputStyle}
              />
            </div>
          ))}
          <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Save</button>
        </form>
      )}
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8, width: '100%' }
