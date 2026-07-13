import React, { useEffect, useState } from 'react'
import { getUsageForIdentity } from '../../api/aiUsage'

export default function AiUsageDetail({ identityId }) {
  const [usage, setUsage] = useState(null)

  useEffect(() => { getUsageForIdentity(identityId).then(setUsage) }, [identityId])

  if (!usage) return <div>Loading…</div>

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 14, fontSize: 13 }}>
        This identity's own LLM usage — every Gemini call triggered on its behalf (auto-reply
        drafting, translation, language detection).
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-agent">calls</span>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 6 }}>{usage.call_count}</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-id">total tokens</span>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 6 }}>{usage.total_tokens.toLocaleString()}</div>
        </div>
        <div className="card" style={{ padding: 14 }}>
          <span className="badge badge-account">est. cost</span>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 6 }}>${Number(usage.total_cost).toFixed(6)}</div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {usage.recent.map((r) => (
          <div key={r.id} className="card" style={{ padding: 10, fontSize: 12, display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <span className="badge badge-room">{r.action}</span> {r.model}
              <div style={{ color: 'var(--sub)', marginTop: 3 }}>{new Date(r.created_at).toLocaleString()}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div>{r.total_tokens ?? '—'} tokens</div>
              <div style={{ color: 'var(--sub)' }}>${r.estimated_cost != null ? Number(r.estimated_cost).toFixed(6) : '—'}</div>
            </div>
          </div>
        ))}
        {usage.recent.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No usage recorded for this identity yet.</div>}
      </div>
    </div>
  )
}
