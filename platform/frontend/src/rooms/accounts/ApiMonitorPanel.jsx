import React, { useEffect, useState } from 'react'
import { createApiMonitorEntry, listApiMonitor } from '../../api/accounts'

const HEALTH_BADGE = { healthy: 'badge-agent', degraded: 'badge-pending', down: 'badge-alert', unknown: 'badge-room' }

export default function ApiMonitorPanel() {
  const [entries, setEntries] = useState([])
  const [form, setForm] = useState({ service_name: '', credit_remaining: '', monthly_limit: '', health_status: 'healthy' })
  const [error, setError] = useState('')

  async function refresh() {
    setEntries(await listApiMonitor())
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createApiMonitorEntry({
        ...form,
        credit_remaining: form.credit_remaining || null,
        monthly_limit: form.monthly_limit || null,
      })
      setForm({ service_name: '', credit_remaining: '', monthly_limit: '', health_status: 'healthy' })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add service')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Available credit, usage, and health for every connected service — so nothing is
        unexpectedly interrupted.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        <input placeholder="Service name" required value={form.service_name} onChange={(e) => setForm({ ...form, service_name: e.target.value })} style={inputStyle} />
        <select value={form.health_status} onChange={(e) => setForm({ ...form, health_status: e.target.value })} style={inputStyle}>
          {Object.keys(HEALTH_BADGE).map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
        <input placeholder="Credit remaining" type="number" step="0.01" value={form.credit_remaining} onChange={(e) => setForm({ ...form, credit_remaining: e.target.value })} style={inputStyle} />
        <input placeholder="Monthly limit" type="number" step="0.01" value={form.monthly_limit} onChange={(e) => setForm({ ...form, monthly_limit: e.target.value })} style={inputStyle} />
        <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Add service</button>
      </form>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        {entries.map((e) => (
          <div key={e.id} className="card" style={{ padding: 14 }}>
            <span className={`badge ${HEALTH_BADGE[e.health_status]}`}>{e.health_status}</span>
            <div style={{ fontWeight: 700, marginTop: 8 }}>{e.service_name}</div>
            {e.credit_remaining != null && (
              <div style={{ fontSize: 12, color: 'var(--sub)' }}>
                {e.credit_remaining} / {e.monthly_limit ?? '—'} remaining
              </div>
            )}
          </div>
        ))}
        {entries.length === 0 && <div style={{ color: 'var(--sub)' }}>No services monitored yet.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
