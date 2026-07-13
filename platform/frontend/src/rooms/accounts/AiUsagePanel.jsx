import React, { useEffect, useState } from 'react'
import { getUsageSummary } from '../../api/aiUsage'

export default function AiUsagePanel() {
  const [rows, setRows] = useState(null)

  useEffect(() => { getUsageSummary().then(setRows) }, [])

  if (!rows) return <div>Loading…</div>

  const totalTokens = rows.reduce((sum, r) => sum + r.total_tokens, 0)
  const totalCost = rows.reduce((sum, r) => sum + Number(r.total_cost), 0)
  const totalCalls = rows.reduce((sum, r) => sum + r.call_count, 0)

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Token usage per identity, recorded from every real LLM call (Gemini reply drafting,
        translation, language detection). This is recording only — no limit is enforced yet;
        a future cap would read these totals before allowing a call through the gate.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-agent">calls</span>
          <div style={{ fontSize: 22, fontWeight: 800, marginTop: 8 }}>{totalCalls}</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-id">total tokens</span>
          <div style={{ fontSize: 22, fontWeight: 800, marginTop: 8 }}>{totalTokens.toLocaleString()}</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-account">estimated cost</span>
          <div style={{ fontSize: 22, fontWeight: 800, marginTop: 8 }}>${totalCost.toFixed(4)}</div>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--neutral-bg)', textAlign: 'left' }}>
              <th style={cellStyle}>Identity</th>
              <th style={cellStyle}>Calls</th>
              <th style={cellStyle}>Total tokens</th>
              <th style={cellStyle}>Estimated cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.identity_id || 'unknown'} style={{ borderTop: '1px solid var(--line)' }}>
                <td style={cellStyle}>{r.identity_name || r.identity_id || '—'}</td>
                <td style={cellStyle}>{r.call_count}</td>
                <td style={cellStyle}>{r.total_tokens.toLocaleString()}</td>
                <td style={cellStyle}>${Number(r.total_cost).toFixed(6)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td style={cellStyle} colSpan={4}>No LLM usage recorded yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const cellStyle = { padding: '10px 14px' }
