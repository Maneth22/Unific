import React, { useState } from 'react'
import { createStaff, grantRoomAccess } from '../api/auth'

const ROOMS = ['accounts', 'profiles', 'meeting_room', 'initial_tasking', 'specialise', 'resources', 'assets', 'hold_data']
const PERMISSIONS = ['read', 'write', 'admin']

export default function StaffManagementPage() {
  const [form, setForm] = useState({ email: '', password: '', full_name: '' })
  const [created, setCreated] = useState(null)
  const [grantForm, setGrantForm] = useState({ staffId: '', room: 'accounts', permission: 'read' })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      const staff = await createStaff(form.email, form.password, form.full_name)
      setCreated(staff)
      setGrantForm((g) => ({ ...g, staffId: staff.id }))
      setForm({ email: '', password: '', full_name: '' })
      setMessage(`Created ${staff.email}. Now grant room access below.`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create staff account')
    }
  }

  async function handleGrant(e) {
    e.preventDefault()
    setError('')
    try {
      const staff = await grantRoomAccess(grantForm.staffId, grantForm.room, grantForm.permission)
      setMessage(`${staff.email} now has ${grantForm.permission} access to ${grantForm.room}.`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not grant room access')
    }
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Staff &amp; Access</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 24 }}>
        There is no open self-registration for staff accounts — the Accounts Room is the highest-
        sensitivity module in the system, so master-dashboard accounts are provisioned
        deliberately, one room grant at a time.
      </p>

      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{message}</div>}
      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 18, marginBottom: 20 }}>
        <div style={{ fontWeight: 700, marginBottom: 12 }}>Create staff account</div>
        <input
          placeholder="Full name"
          required
          value={form.full_name}
          onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          style={{ width: '100%', padding: 8, marginBottom: 8, border: '1px solid var(--line)', borderRadius: 8 }}
        />
        <input
          type="email"
          placeholder="Email"
          required
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          style={{ width: '100%', padding: 8, marginBottom: 8, border: '1px solid var(--line)', borderRadius: 8 }}
        />
        <input
          type="password"
          placeholder="Temporary password (12+ chars)"
          required
          minLength={12}
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          style={{ width: '100%', padding: 8, marginBottom: 12, border: '1px solid var(--line)', borderRadius: 8 }}
        />
        <button type="submit" className="btn btn-primary">Create</button>
        {created && (
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--sub)' }}>
            Created id: <code>{created.id}</code>
          </div>
        )}
      </form>

      <form onSubmit={handleGrant} className="card" style={{ padding: 18 }}>
        <div style={{ fontWeight: 700, marginBottom: 12 }}>Grant room access</div>
        <input
          placeholder="Staff ID"
          required
          value={grantForm.staffId}
          onChange={(e) => setGrantForm({ ...grantForm, staffId: e.target.value })}
          style={{ width: '100%', padding: 8, marginBottom: 8, border: '1px solid var(--line)', borderRadius: 8 }}
        />
        <select
          value={grantForm.room}
          onChange={(e) => setGrantForm({ ...grantForm, room: e.target.value })}
          style={{ width: '100%', padding: 8, marginBottom: 8, border: '1px solid var(--line)', borderRadius: 8 }}
        >
          {ROOMS.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <select
          value={grantForm.permission}
          onChange={(e) => setGrantForm({ ...grantForm, permission: e.target.value })}
          style={{ width: '100%', padding: 8, marginBottom: 12, border: '1px solid var(--line)', borderRadius: 8 }}
        >
          {PERMISSIONS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary">Grant</button>
      </form>
    </div>
  )
}
