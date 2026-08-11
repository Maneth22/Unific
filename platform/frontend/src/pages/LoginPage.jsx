import React, { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Where a signed-in staff account lands with no more specific destination
// (no `location.state.from`, i.e. they came straight here rather than
// being bounced off a protected route) — admin tier gets the full
// dashboard, everyone else gets the portal, since /staff is gated by
// RequireAdmin and would otherwise bounce a non-admin straight to /403.
function defaultDestinationFor(staff) {
  return staff?.tier === 'admin' ? '/staff' : '/portal'
}

export default function LoginPage() {
  const { isAuthenticated, staff, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const idleSignOut = searchParams.get('reason') === 'idle'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) {
    return <Navigate to={location.state?.from?.pathname || defaultDestinationFor(staff)} replace />
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const data = await login(email, password)
      navigate(location.state?.from?.pathname || defaultDestinationFor(data.staff), { replace: true })
    } catch (err) {
      if (err.response?.status === 429) {
        setError('Too many failed attempts. Try again later.')
      } else {
        setError('Invalid email or password.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <form onSubmit={handleSubmit} className="card" style={{ width: 340, padding: 28 }}>
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>UNIFIC Platform</div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: 20 }}>
          Staff &amp; supporter sign in
        </div>

        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>
          Email
        </label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 10px',
            marginBottom: 14,
            border: '1px solid var(--line)',
            borderRadius: 8,
          }}
        />

        <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>
          Password
        </label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 10px',
            marginBottom: 16,
            border: '1px solid var(--line)',
            borderRadius: 8,
          }}
        />

        {!error && idleSignOut && (
          <div className="badge badge-pending" style={{ display: 'block', marginBottom: 14 }}>
            You were signed out due to inactivity.
          </div>
        )}

        {error && (
          <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>

        <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12 }}>
          <Link to="/login">Client, not staff? Sign in here</Link>
        </div>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 12 }}>
          <Link to="/">← Back to home</Link>
        </div>
      </form>
    </div>
  )
}
