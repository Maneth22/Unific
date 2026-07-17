import React, { useState } from 'react'
import { createStaff } from '../api/auth'

export default function StaffManagementPage() {
  const [form, setForm] = useState({ email: '', password: '', full_name: '' })
  const [created, setCreated] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      const staff = await createStaff(form.email, form.password, form.full_name)
      setCreated(staff)
      setForm({ email: '', password: '', full_name: '' })
      setMessage(`Created ${staff.email} — a full Admin account, active immediately.`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create staff account')
    }
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Staff &amp; Access</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 24 }}>
        There is no open self-registration for staff accounts — every staff account is a full
        Admin with access to every room, so accounts are provisioned deliberately by an existing
        Admin, not signed up for.
      </p>

      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{message}</div>}
      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 18 }}>
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
    </div>
  )
}
