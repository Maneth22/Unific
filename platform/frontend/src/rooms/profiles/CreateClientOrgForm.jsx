import React, { useState } from 'react'
import { createClientOrg } from '../../api/profiles'

// Client orgs are always identity-tree roots with a richer field set than
// a plain group — a dedicated form rather than folding this into
// IdentityTree.jsx's generic "Add identity" (name/type/parent) form.
export default function CreateClientOrgForm({ onCreated }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', entity_type: '', role_description: '', abn_acnc_number: '' })
  const [created, setCreated] = useState(null)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    try {
      const identity = await createClientOrg({ ...form, abn_acnc_number: form.abn_acnc_number || null })
      setCreated(identity)
      setForm({ name: '', entity_type: '', role_description: '', abn_acnc_number: '' })
      onCreated?.()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create client organization')
    }
  }

  return (
    <div className="card" style={{ padding: 14, marginBottom: 14 }}>
      <div
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        <div style={{ fontWeight: 700, fontSize: 13 }}>Create client organization</div>
        <span style={{ fontSize: 12, color: 'var(--sub)' }}>{open ? 'Hide' : 'New'}</span>
      </div>

      {open && (
        <form onSubmit={handleSubmit} style={{ marginTop: 12, display: 'grid', gap: 8 }}>
          {error && <div className="badge badge-alert" style={{ display: 'block', padding: '8px 12px' }}>{error}</div>}
          {created && <div className="badge badge-agent" style={{ display: 'block', padding: '8px 12px' }}>Created — Group ID assigned.</div>}
          <input required placeholder="Name — e.g. LandChange Ltd" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={inputStyle} />
          <input placeholder="Entity type — e.g. ACNC-registered not-for-profit (Australia)" value={form.entity_type} onChange={(e) => setForm({ ...form, entity_type: e.target.value })} style={inputStyle} />
          <input placeholder="Role — e.g. client of UNIFIC; funding arm; community centre network" value={form.role_description} onChange={(e) => setForm({ ...form, role_description: e.target.value })} style={inputStyle} />
          <input placeholder="ABN / ACNC number (optional)" value={form.abn_acnc_number} onChange={(e) => setForm({ ...form, abn_acnc_number: e.target.value })} style={inputStyle} />
          <button type="submit" className="btn btn-primary">Create</button>
        </form>
      )}
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
