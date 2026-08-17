import React, { useEffect, useState } from 'react'
import { getWhatsAppWebhookLog } from '../../api/accounts'

// Raw wire traffic (core.webhook_log) — the only place a rejected message
// shows up at all: an unlinked phone number, a gate/charge block, or a
// malformed payload never becomes a Conversation/Message (see
// ConversationsView), so checking "did this test actually reach us" often
// means checking here instead. Same rendering as
// rooms/accounts/WhatsAppDiagnosticsPanel.jsx's "Recent webhook traffic"
// section, reused directly since it's the same underlying log across the
// whole app, not room-scoped.
export default function WebhookLogView() {
  const [log, setLog] = useState([])
  const [expandedId, setExpandedId] = useState('')
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  async function refresh() {
    setError('')
    setRefreshing(true)
    try {
      setLog(await getWhatsAppWebhookLog(50))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load webhook log')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => { refresh() }, [])

  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Recent webhook traffic</div>
        <button className="btn" onClick={refresh} disabled={refreshing} style={{ fontSize: 11, padding: '4px 10px' }}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <p style={{ color: 'var(--sub)', fontSize: 12, marginBottom: 10 }}>
        Every inbound/outbound WhatsApp payload, logged unconditionally — including messages that
        never became a conversation (unlinked number, blocked, malformed payload).
      </p>
      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
      <div style={{ maxHeight: 520, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {log.map((entry) => (
          <div key={entry.id} className="card card-clickable" style={{ padding: 10 }} onClick={() => setExpandedId(expandedId === entry.id ? '' : entry.id)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <div>
                <span className={`badge ${entry.direction === 'inbound' ? 'badge-id' : 'badge-account'}`} style={{ marginRight: 6 }}>
                  {entry.direction}
                </span>
                <span
                  className={`badge ${entry.status.startsWith('error') || entry.status === 'invalid_object' ? 'badge-alert' : 'badge-agent'}`}
                  style={{ marginRight: 6 }}
                >
                  {entry.status}
                </span>
                <span style={{ fontSize: 12, color: 'var(--sub)' }}>{entry.provider}</span>
              </div>
              <span style={{ fontSize: 11, color: 'var(--sub)', whiteSpace: 'nowrap' }}>
                {new Date(entry.created_at).toLocaleString()}
              </span>
            </div>
            {expandedId === entry.id && (
              <pre
                style={{
                  marginTop: 8, padding: 10, background: 'var(--neutral-bg)', borderRadius: 6,
                  fontSize: 11, overflowX: 'auto', maxHeight: 300,
                }}
              >
                {JSON.stringify(entry.raw_payload, null, 2)}
              </pre>
            )}
          </div>
        ))}
        {log.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No webhook traffic logged yet.</div>}
      </div>
    </div>
  )
}
