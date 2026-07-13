import React, { useEffect, useState } from 'react'
import { useClientAuth } from '../context/ClientAuthContext'
import { getAccountsOverview, fundMyAccount, transferMyCredit, getMyPermission, updateMyPermission } from '../api/clientProfiles'

export default function ClientAccountsPage() {
  const { clientUser } = useClientAuth()
  const rootId = clientUser.identity_id

  const [overview, setOverview] = useState(null)
  const [permission, setPermission] = useState(null)
  const [fundAmount, setFundAmount] = useState('')
  const [transferTo, setTransferTo] = useState('')
  const [transferAmount, setTransferAmount] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    const [o, p] = await Promise.all([getAccountsOverview(), getMyPermission(rootId)])
    setOverview(o)
    setPermission(p)
  }

  useEffect(() => { refresh() }, [])

  async function handleFund(e) {
    e.preventDefault()
    setError(''); setMessage('')
    try {
      await fundMyAccount(rootId, fundAmount)
      setFundAmount('')
      refresh()
      setMessage('Tokens added to your community account.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add tokens')
    }
  }

  async function handleTransfer(e) {
    e.preventDefault()
    setError(''); setMessage('')
    try {
      await transferMyCredit(rootId, transferTo, transferAmount)
      setTransferTo(''); setTransferAmount('')
      refresh()
      setMessage('Sent.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send credit')
    }
  }

  if (!overview) return <div>Loading…</div>

  const own = overview.community_accounts.find((a) => a.is_own)
  const others = overview.community_accounts.filter((a) => !a.is_own)

  return (
    <div style={{ maxWidth: 860 }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Accounts</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        Your community's accounts, the services running behind them, and your AI usage — all in one place.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}
      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{message}</div>}

      {/* --- Community accounts --- */}
      <SectionTitle>Community accounts</SectionTitle>
      <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 14 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--neutral-bg)', textAlign: 'left' }}>
              <th style={cell}>Name</th>
              <th style={cell}>Type</th>
              <th style={{ ...cell, textAlign: 'right' }}>Balance</th>
            </tr>
          </thead>
          <tbody>
            {overview.community_accounts.map((a) => (
              <tr key={a.identity_id} style={{ borderTop: '1px solid var(--line)' }}>
                <td style={cell}>{a.name} {a.is_own && <span className="badge badge-account">your account</span>}</td>
                <td style={cell}>{a.id_type}</td>
                <td style={{ ...cell, textAlign: 'right', fontWeight: 700 }}>${Number(a.balance).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 24 }}>
        <form onSubmit={handleFund} className="card" style={{ padding: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Add tokens to your account</div>
          <input placeholder="Amount" type="number" step="0.01" required value={fundAmount} onChange={(e) => setFundAmount(e.target.value)} style={input} />
          <button type="submit" className="btn btn-primary" style={{ marginTop: 8 }}>Add tokens</button>
          {permission?.effective_credit_cap && (
            <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 6 }}>
              Cap: ${Number(permission.effective_credit_cap).toFixed(2)}
            </div>
          )}
        </form>
        <form onSubmit={handleTransfer} className="card" style={{ padding: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Send to a group or member</div>
          <select required value={transferTo} onChange={(e) => setTransferTo(e.target.value)} style={input}>
            <option value="">— select —</option>
            {others.map((a) => <option key={a.identity_id} value={a.identity_id}>{a.name}</option>)}
          </select>
          <input placeholder="Amount" type="number" step="0.01" required value={transferAmount} onChange={(e) => setTransferAmount(e.target.value)} style={{ ...input, marginTop: 6 }} />
          <button type="submit" className="btn btn-primary" style={{ marginTop: 8 }}>Send</button>
        </form>
      </div>

      {/* --- AI & service providers --- */}
      <SectionTitle>AI & service providers</SectionTitle>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12, marginBottom: 24 }}>
        {overview.service_providers.map((p) => (
          <div key={p.name} className="card" style={{ padding: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong>{p.name}</strong>
              <span className={`badge ${p.status === 'active' ? 'badge-agent' : 'badge-pending'}`}>{p.status}</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 4 }}>{p.kind}</div>
            <div style={{ fontSize: 12, marginTop: 2, fontFamily: 'monospace' }}>{p.model}</div>
          </div>
        ))}
      </div>

      {/* --- Gemini token dashboard --- */}
      <SectionTitle>AI token usage</SectionTitle>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-id">total tokens used</span>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{overview.ai_total_tokens.toLocaleString()}</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-account">estimated cost</span>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>${Number(overview.ai_total_cost).toFixed(4)}</div>
        </div>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--neutral-bg)', textAlign: 'left' }}>
              <th style={cell}>Member / group</th>
              <th style={cell}>AI calls</th>
              <th style={cell}>Tokens</th>
              <th style={{ ...cell, textAlign: 'right' }}>Est. cost</th>
            </tr>
          </thead>
          <tbody>
            {overview.ai_usage.map((u) => (
              <tr key={u.identity_id || 'x'} style={{ borderTop: '1px solid var(--line)' }}>
                <td style={cell}>{u.identity_name || '—'}</td>
                <td style={cell}>{u.call_count}</td>
                <td style={cell}>{u.total_tokens.toLocaleString()}</td>
                <td style={{ ...cell, textAlign: 'right' }}>${Number(u.total_cost).toFixed(4)}</td>
              </tr>
            ))}
            {overview.ai_usage.length === 0 && (
              <tr><td style={cell} colSpan={4}>No AI usage yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SectionTitle({ children }) {
  return <div style={{ fontWeight: 800, fontSize: 13, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: 0.4, color: 'var(--sub)' }}>{children}</div>
}

const cell = { padding: '9px 14px' }
const input = { padding: 8, border: '1px solid var(--line)', borderRadius: 8, width: '100%', fontSize: 13 }
