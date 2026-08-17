import React, { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useClientAuth } from '../context/ClientAuthContext'
import AuthSplitScreen from '../layouts/shared/AuthSplitScreen.jsx'
import Card from '../components/ui/Card.jsx'
import Input from '../components/ui/Input.jsx'
import Button from '../components/ui/Button.jsx'

const ACTOR_TYPES = [
  { value: 'owner', label: 'Org owner' },
  { value: 'staff', label: 'Staff member' },
]

export default function ClientLoginPage() {
  const { isAuthenticated, login } = useClientAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const idleSignOut = searchParams.get('reason') === 'idle'
  const [actorType, setActorType] = useState('owner')
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
      await login(email, password, actorType)
      navigate('/client', { replace: true })
    } catch (err) {
      setError(err.response?.status === 429 ? 'Too many failed attempts. Try again later.' : 'Invalid email or password.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthSplitScreen
      heading="Accountable technology for community-led development"
      subheading="UNIFIC gives organisations and the communities they serve one shared, verifiable platform for accounts, identity, and communication."
    >
      <Card className="auth-split-form-card">
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>UNIFIC</div>
        <div style={{ color: 'var(--sub)', fontSize: 13, marginBottom: 20 }}>Your account dashboard</div>

        <div className="ui-segmented" style={{ width: '100%', marginBottom: 16 }}>
          {ACTOR_TYPES.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setActorType(opt.value)}
              className={`ui-segmented-btn${actorType === opt.value ? ' ui-segmented-btn--active' : ''}`}
              style={{ flex: 1 }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <Input label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>

          <div style={{ marginBottom: 16 }}>
            <Input
              label="Password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {!error && idleSignOut && (
            <div className="badge badge-pending" style={{ display: 'block', marginBottom: 14 }}>
              You were signed out due to inactivity.
            </div>
          )}

          {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14 }}>{error}</div>}

          <Button type="submit" variant="primary" loading={submitting} style={{ width: '100%' }}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12 }}>
          <Link to="/client/signup">Don't have an account? Register your organisation</Link>
        </div>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 12 }}>
          <Link to="/support/login">Staff &amp; Partners? Sign in here</Link>
        </div>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 12 }}>
          <Link to="/">← Back to home</Link>
        </div>
      </Card>
    </AuthSplitScreen>
  )
}
