import React, { useEffect, useState } from 'react'
import { listConsent, recordConsent } from '../../api/profiles'

export default function ConsentPanel({ identityId }) {
  const [records, setRecords] = useState([])
  const [form, setForm] = useState({ context: 'onboarding', granted: true, retention_period: '', data_residency: '', note: '' })
  const [error, setError] = useState('')

  async function refresh() {
    setRecords(await listConsent(identityId))
  }

  useEffect(() => { refresh() }, [identityId])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    try {
      await recordConsent(identityId, form)
      setForm({ context: 'onboarding', granted: true, retention_period: '', data_residency: '', note: '' })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not record consent')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 14, fontSize: 13 }}>
        Recording, transcription, and deep profiling require explicit consent — captured here at
        onboarding or at record time, with retention and residency logged alongside it.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}

      <form onSubmit={handleSubmit} className="card" style={{ padding: 14, marginBottom: 16, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        <select value={form.context} onChange={(e) => setForm({ ...form, context: e.target.value })} style={inputStyle}>
          <option value="onboarding">onboarding</option>
          <option value="record_time">record_time</option>
        </select>
        <select value={String(form.granted)} onChange={(e) => setForm({ ...form, granted: e.target.value === 'true' })} style={inputStyle}>
          <option value="true">granted</option>
          <option value="false">withheld</option>
        </select>
        <input placeholder="Retention period (e.g. 3 years)" value={form.retention_period} onChange={(e) => setForm({ ...form, retention_period: e.target.value })} style={inputStyle} />
        <input placeholder="Data residency (e.g. India)" value={form.data_residency} onChange={(e) => setForm({ ...form, data_residency: e.target.value })} style={inputStyle} />
        <input placeholder="Note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} style={{ ...inputStyle, gridColumn: '1 / -1' }} />
        <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Record consent</button>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {records.map((r) => (
          <div key={r.id} className="card" style={{ padding: 10, fontSize: 12 }}>
            <span className={`badge ${r.granted ? 'badge-agent' : 'badge-alert'}`}>{r.granted ? 'granted' : 'withheld'}</span>{' '}
            <span className="badge badge-room">{r.context}</span>
            <div style={{ color: 'var(--sub)', marginTop: 4 }}>
              {r.retention_period && `retention: ${r.retention_period} · `}
              {r.data_residency && `residency: ${r.data_residency} · `}
              {new Date(r.granted_at).toLocaleString()}
            </div>
          </div>
        ))}
        {records.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No consent records yet.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8, fontSize: 13 }
