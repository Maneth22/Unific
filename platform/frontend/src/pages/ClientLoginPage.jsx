import React, { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useClientAuth } from '../context/ClientAuthContext'

export default function ClientLoginPage() {
  const { isAuthenticated, login } = useClientAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) return <Navigate to="/client" replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
      navigate('/client', { replace: true })
    } catch (err) {
      setError(err.response?.status === 429 ? 'Too many failed attempts. Try again later.' : 'Invalid email or password.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <form onSubmit={handleSubmit} className="card" style={{ width: 340, padding: 28 }}>
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>UNIFIC</div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: 20 }}>Your account dashboard</div>

        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ width: '100%', padding: '8px 10px', marginBottom: 14, border: '1px solid var(--line)', borderRadius: 8 }}
        />

        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Password</label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ width: '100%', padding: '8px 10px', marginBottom: 16, border: '1px solid var(--line)', borderRadius: 8 }}
        />

        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>{error}</div>}

        <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
