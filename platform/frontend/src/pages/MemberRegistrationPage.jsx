import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getInviteInfo, submitMemberRegistration } from '../api/publicRegistration'

// Fully public — no auth wrapper, no nav chrome. A community member reaches
// this page from a link the client shares (e.g. over WhatsApp/SMS/in
// person). Submitting hard-redirects the browser straight into a WhatsApp
// chat with the personal agent — there's no dashboard to land in.
export default function MemberRegistrationPage() {
  const { token } = useParams()
  const [groupInfo, setGroupInfo] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [form, setForm] = useState({ name: '', email: '', mobile_number: '', ilc_registration_number: '', notes: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getInviteInfo(token)
      .then(setGroupInfo)
      .catch(() => setLoadError('This registration link is invalid or has expired.'))
  }, [token])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const { notes, ...rest } = form
      const payload = { ...rest, extra_info: notes ? { notes } : {} }
      const result = await submitMemberRegistration(token, payload)
      window.location.href = result.whatsapp_url
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not complete registration')
      setSubmitting(false)
    }
  }

  if (loadError) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ width: 340, padding: 28, textAlign: 'center', color: 'var(--sub)' }}>{loadError}</div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <form onSubmit={handleSubmit} className="card" style={{ width: 380, padding: 28 }}>
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>
          {groupInfo ? groupInfo.group_name : 'Loading…'}
        </div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: 20 }}>
          {groupInfo ? `Register with ${groupInfo.org_name} to start chatting with your personal agent.` : ''}
        </div>

        <label style={labelStyle}>Your name</label>
        <input
          required
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Mobile number (WhatsApp)</label>
        <input
          required
          placeholder="+91…"
          value={form.mobile_number}
          onChange={(e) => setForm({ ...form, mobile_number: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Your registration number</label>
        <input
          required
          placeholder="Given to you by your ILC group"
          value={form.ilc_registration_number}
          onChange={(e) => setForm({ ...form, ilc_registration_number: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Email (optional)</label>
        <input
          type="email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Anything else you'd like to share (optional)</label>
        <input
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          style={{ ...inputStyle, marginBottom: 16 }}
        />

        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>{error}</div>}

        <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={submitting || !groupInfo}>
          {submitting ? 'Taking you to WhatsApp…' : 'Register and start chatting'}
        </button>
      </form>
    </div>
  )
}

const inputStyle = { width: '100%', padding: '8px 10px', marginBottom: 14, border: '1px solid var(--line)', borderRadius: 8 }
const labelStyle = { fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }
