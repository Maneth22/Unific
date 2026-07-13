import React, { useEffect, useState } from 'react'
import { createFinancialRecord, getFinancialSummary, listFinancialRecords } from '../../api/accounts'

const CATEGORIES = ['subscription', 'salary', 'contractor', 'api_usage', 'hosting', 'other']

export default function FinancialDashboard() {
  const [summary, setSummary] = useState(null)
  const [records, setRecords] = useState([])
  const [form, setForm] = useState({ category: 'subscription', description: '', amount: '', incurred_at: new Date().toISOString().slice(0, 10) })
  const [error, setError] = useState('')

  async function refresh() {
    const [s, r] = await Promise.all([getFinancialSummary(), listFinancialRecords()])
    setSummary(s)
    setRecords(r)
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createFinancialRecord({ ...form, amount: form.amount })
      setForm({ category: 'subscription', description: '', amount: '', incurred_at: new Date().toISOString().slice(0, 10) })
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not record expense')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Every operational expense — subscriptions, salaries, contractors, API usage — plus every
        agent's automatic spend from the Token Ledger below.
      </p>

      {summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
          <StatCard label="Manual expenses" value={`$${Number(summary.total_manual_expenses).toFixed(2)}`} badge="badge-account" />
          <StatCard label="Agent spend (token ledger)" value={`$${Number(summary.total_agent_spend).toFixed(2)}`} badge="badge-agent" />
          {Object.entries(summary.by_category).map(([cat, amt]) => (
            <StatCard key={cat} label={cat} value={`$${Number(amt).toFixed(2)}`} badge="badge-room" />
          ))}
        </div>
      )}

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} style={inputStyle}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input type="date" required value={form.incurred_at} onChange={(e) => setForm({ ...form, incurred_at: e.target.value })} style={inputStyle} />
        <input placeholder="Description" required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ ...inputStyle, gridColumn: '1 / -1' }} />
        <input placeholder="Amount" type="number" step="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} style={inputStyle} />
        <button type="submit" className="btn btn-primary">Record expense</button>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {records.map((r) => (
          <div key={r.id} className="card" style={{ padding: 12, display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <span className="badge badge-room">{r.category}</span> {r.description}
              <div style={{ fontSize: 12, color: 'var(--sub)' }}>{r.incurred_at}</div>
            </div>
            <strong>${Number(r.amount).toFixed(2)}</strong>
          </div>
        ))}
      </div>

      {summary && (
        <div style={{ marginTop: 24 }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Token Ledger — room accounts</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            {summary.room_summaries.map((rs) => (
              <div key={rs.room} className="card" style={{ padding: 14 }}>
                <span className="badge badge-room">{rs.room}</span>
                <div style={{ fontSize: 20, fontWeight: 800, marginTop: 6 }}>${Number(rs.balance).toFixed(2)}</div>
                {rs.agents.map((a) => (
                  <div key={a.agent_name} style={{ fontSize: 12, color: 'var(--sub)', display: 'flex', justifyContent: 'space-between' }}>
                    <span>{a.agent_name}</span>
                    <span>${Number(a.balance).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, badge }) {
  return (
    <div className="card" style={{ padding: 14 }}>
      <span className={`badge ${badge}`}>{label}</span>
      <div style={{ fontSize: 20, fontWeight: 800, marginTop: 8 }}>{value}</div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
