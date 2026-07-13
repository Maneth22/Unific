import React, { useEffect, useState } from 'react'
import { createClientAccount, fundAccount, getAccount, transferCredit } from '../../api/profiles'

export default function ProfileAccountPanel({ identityId }) {
  const [account, setAccount] = useState(null)
  const [fundAmount, setFundAmount] = useState('')
  const [transferTo, setTransferTo] = useState('')
  const [transferAmount, setTransferAmount] = useState('')
  const [clientForm, setClientForm] = useState({ email: '', password: '', full_name: '' })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    setAccount(await getAccount(identityId))
  }

  useEffect(() => { setMessage(''); setError(''); refresh() }, [identityId])

  async function handleFund(e) {
    e.preventDefault()
    setError(''); setMessage('')
    try {
      await fundAccount(identityId, fundAmount)
      setFundAmount('')
      refresh()
      setMessage('Funded.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not fund account')
    }
  }

  async function handleTransfer(e) {
    e.preventDefault()
    setError(''); setMessage('')
    try {
      await transferCredit(identityId, transferTo, transferAmount)
      setTransferTo(''); setTransferAmount('')
      refresh()
      setMessage('Trickled down to descendant.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not transfer credit')
    }
  }

  async function handleCreateClient(e) {
    e.preventDefault()
    setError(''); setMessage('')
    try {
      const client = await createClientAccount(identityId, clientForm)
      setClientForm({ email: '', password: '', full_name: '' })
      setMessage(`Client dashboard login created: ${client.email}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create client account')
    }
  }

  if (!account) return <div>Loading…</div>

  return (
    <div>
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <span className="badge badge-account">balance</span>
        <div style={{ fontSize: 28, fontWeight: 800, marginTop: 6 }}>${Number(account.balance).toFixed(2)}</div>
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{message}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <form onSubmit={handleFund} className="card" style={{ padding: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Fund this identity</div>
          <input placeholder="Amount" type="number" step="0.01" required value={fundAmount} onChange={(e) => setFundAmount(e.target.value)} style={inputStyle} />
          <button type="submit" className="btn btn-primary" style={{ marginTop: 8 }}>Fund</button>
        </form>

        <form onSubmit={handleTransfer} className="card" style={{ padding: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Trickle down to a descendant</div>
          <input placeholder="Descendant identity ID" required value={transferTo} onChange={(e) => setTransferTo(e.target.value)} style={inputStyle} />
          <input placeholder="Amount" type="number" step="0.01" required value={transferAmount} onChange={(e) => setTransferAmount(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} />
          <button type="submit" className="btn btn-primary" style={{ marginTop: 8 }}>Transfer</button>
        </form>
      </div>

      <form onSubmit={handleCreateClient} className="card" style={{ padding: 14, marginTop: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Provision a client-dashboard login for this identity</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          <input placeholder="Full name" required value={clientForm.full_name} onChange={(e) => setClientForm({ ...clientForm, full_name: e.target.value })} style={inputStyle} />
          <input placeholder="Email" type="email" required value={clientForm.email} onChange={(e) => setClientForm({ ...clientForm, email: e.target.value })} style={inputStyle} />
          <input placeholder="Temp password (12+)" type="password" required minLength={12} value={clientForm.password} onChange={(e) => setClientForm({ ...clientForm, password: e.target.value })} style={inputStyle} />
        </div>
        <button type="submit" className="btn btn-primary" style={{ marginTop: 8 }}>Create client login</button>
      </form>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8, fontSize: 13, width: '100%' }
