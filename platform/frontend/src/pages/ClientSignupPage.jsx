import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { submitClientSignup } from '../api/publicRegistration'

export default function ClientSignupPage() {
  const [form, setForm] = useState({ org_name: '', contact_name: '', email: '', password: '' })
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await submitClientSignup(form)
      setSubmitted(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not submit registration')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ width: 380, padding: 28, textAlign: 'center' }}>
          <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 8 }}>Registration submitted</div>
          <p style={{ color: 'var(--sub)', fontSize: 13 }}>
            An Admin needs to review and approve your organisation before you can log in. You'll be
            notified once it's approved.
          </p>
          <Link to="/client/login" className="btn" style={{ display: 'inline-block', marginTop: 14 }}>
            Back to login
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <form onSubmit={handleSubmit} className="card" style={{ width: 380, padding: 28 }}>
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>Register your organisation</div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: 20 }}>
          Submitted for Admin approval — you'll get dashboard access once it's reviewed.
        </div>

        <label style={labelStyle}>Organisation name</label>
        <input
          required
          placeholder="e.g. LandChange"
          value={form.org_name}
          onChange={(e) => setForm({ ...form, org_name: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Your name</label>
        <input
          required
          value={form.contact_name}
          onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Email</label>
        <input
          type="email"
          required
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          style={inputStyle}
        />

        <label style={labelStyle}>Password (12+ characters)</label>
        <input
          type="password"
          required
          minLength={12}
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          style={{ ...inputStyle, marginBottom: 16 }}
        />

        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>{error}</div>}

        <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={submitting}>
          {submitting ? 'Submitting…' : 'Submit for approval'}
        </button>

        <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12 }}>
          <Link to="/client/login">Already approved? Sign in</Link>
        </div>
      </form>
    </div>
  )
}

const inputStyle = { width: '100%', padding: '8px 10px', marginBottom: 14, border: '1px solid var(--line)', borderRadius: 8 }
const labelStyle = { fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }
