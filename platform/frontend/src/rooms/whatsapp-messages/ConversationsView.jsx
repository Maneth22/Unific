import React, { useEffect, useRef, useState } from 'react'
import { flushWhatsAppSessions, getConversation, listConversations } from '../../api/meetingRoom'

// Read-focused sibling of Meeting Room's ChatView.jsx — no manual-reply or
// simulate-inbound tooling here (that stays on Chat, the operational
// surface); this one exists purely to answer "did the WhatsApp interface
// actually work for this message," so it leans on flush + auto-refresh to
// surface today's messages immediately instead of waiting for the
// end-of-day cron (see api/meetingRoom.js's flushWhatsAppSessions).
export default function ConversationsView() {
  const [conversations, setConversations] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const busy = useRef(false)

  const visibleConversations = conversations.filter((c) =>
    (c.identity_name || c.identity_id).toLowerCase().includes(searchTerm.toLowerCase()),
  )

  async function refreshList() {
    setConversations(await listConversations())
  }

  useEffect(() => { refreshList() }, [])

  useEffect(() => {
    if (selectedId) getConversation(selectedId).then(setDetail).catch(() => {})
  }, [selectedId])

  // Keeps the list current without a manual reload — paused while a
  // flush/refresh is already in flight so requests don't pile up.
  useEffect(() => {
    const id = setInterval(() => { if (!busy.current) refreshList() }, 5000)
    return () => clearInterval(id)
  }, [])

  async function handleRefresh() {
    setError('')
    setRefreshing(true)
    busy.current = true
    try {
      // Force today's Redis-cached turns into Postgres first, so a message
      // sent moments ago shows up now instead of at the next EOD flush.
      await flushWhatsAppSessions()
      await refreshList()
      if (selectedId) setDetail(await getConversation(selectedId))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not refresh')
    } finally {
      setRefreshing(false)
      busy.current = false
    }
  }

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div className="card" style={{ width: 260, padding: 12, flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ fontWeight: 700, fontSize: 12 }}>Conversations</div>
          <button className="btn" onClick={handleRefresh} disabled={refreshing} style={{ fontSize: 11, padding: '4px 10px' }}>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        <input
          placeholder="Search by name…"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{ ...smallInput, marginBottom: 8 }}
        />
        {visibleConversations.map((c) => (
          <div
            key={c.id}
            onClick={() => setSelectedId(c.id)}
            style={{
              padding: 8,
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 12,
              background: selectedId === c.id ? 'var(--slate-bg)' : 'transparent',
            }}
          >
            {c.identity_name || `${c.identity_id.slice(0, 8)}…`} <span style={{ color: 'var(--sub)' }}>{c.status}</span>
          </div>
        ))}
        {conversations.length === 0 && (
          <div style={{ color: 'var(--sub)', fontSize: 12 }}>
            No conversations yet — hit Refresh after sending a test message.
          </div>
        )}
        {conversations.length > 0 && visibleConversations.length === 0 && (
          <div style={{ color: 'var(--sub)', fontSize: 12 }}>No conversations match "{searchTerm}".</div>
        )}
      </div>

      <div style={{ flex: 1 }}>
        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
        {!detail ? (
          <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>Select a conversation.</div>
        ) : (
          <div className="card" style={{ padding: 14, maxHeight: 520, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {detail.messages.map((m) => (
              <div
                key={m.id}
                style={{
                  alignSelf: m.direction === 'inbound' ? 'flex-start' : 'flex-end',
                  background: m.direction === 'inbound' ? 'var(--neutral-bg)' : 'var(--token-bg)',
                  padding: '8px 12px',
                  borderRadius: 10,
                  maxWidth: '75%',
                  fontSize: 13,
                }}
              >
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4, flexWrap: 'wrap' }}>
                  {m.mode && <span className="badge badge-agent">{m.mode}</span>}
                  <span style={{ fontSize: 10, color: 'var(--sub)' }}>{new Date(m.created_at).toLocaleString()}</span>
                </div>
                {m.direction === 'inbound' ? (
                  <>
                    <div>{m.translated_text || m.original_text}</div>
                    {m.translated_text && m.translated_text !== m.original_text && (
                      <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>
                        Original{m.detected_language ? ` (${m.detected_language})` : ''}: {m.original_text}
                      </div>
                    )}
                    {m.tone_analysis?.brief_insight && (
                      <div style={{ fontSize: 11, marginTop: 5 }}>
                        {m.tone_analysis.emotional_tone && (
                          <span className="badge badge-pending" style={{ marginRight: 4 }}>{m.tone_analysis.emotional_tone}</span>
                        )}
                        <span style={{ color: 'var(--sub)' }}>{m.tone_analysis.brief_insight}</span>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <div>{m.original_text || m.final_text}</div>
                    {m.translated_text && m.translated_text !== m.original_text && (
                      <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>Sent as: {m.translated_text}</div>
                    )}
                  </>
                )}
                {/* Ties a message back to the raw traffic on the Webhook Log
                    tab, and to the provider's own delivery record. */}
                {m.provider_message_id && (
                  <div style={{ fontSize: 10, color: 'var(--sub)', marginTop: 4 }}>id: {m.provider_message_id}</div>
                )}
              </div>
            ))}
            {detail.messages.length === 0 && (
              <div style={{ color: 'var(--sub)', fontSize: 13 }}>No messages in this conversation yet.</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const smallInput = { padding: 6, border: '1px solid var(--line)', borderRadius: 6, fontSize: 12, width: '100%' }
