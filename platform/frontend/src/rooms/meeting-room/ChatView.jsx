import React, { useEffect, useState } from 'react'
import { getConversation, listConversations, sendManualReply, simulateInboundMessage } from '../../api/meetingRoom'

export default function ChatView() {
  const [conversations, setConversations] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [replyText, setReplyText] = useState('')
  const [simForm, setSimForm] = useState({ from: '', text: '' })
  const [error, setError] = useState('')

  async function refreshList() {
    setConversations(await listConversations())
  }

  useEffect(() => { refreshList() }, [])

  useEffect(() => {
    if (selectedId) getConversation(selectedId).then(setDetail)
  }, [selectedId])

  async function handleReply(e) {
    e.preventDefault()
    setError('')
    try {
      await sendManualReply(selectedId, replyText)
      setReplyText('')
      setDetail(await getConversation(selectedId))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send reply')
    }
  }

  async function handleSimulate(e) {
    e.preventDefault()
    setError('')
    try {
      await simulateInboundMessage(simForm.from, simForm.text)
      setSimForm({ from: simForm.from, text: '' })
      await refreshList()
    } catch (err) {
      setError('Could not simulate message — check the phone number is linked')
    }
  }

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div className="card" style={{ width: 260, padding: 12, flexShrink: 0 }}>
        <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 12 }}>Conversations</div>
        {conversations.map((c) => (
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
            {c.identity_id.slice(0, 8)}… <span style={{ color: 'var(--sub)' }}>{c.status}</span>
          </div>
        ))}
        {conversations.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 12 }}>No conversations yet.</div>}

        <form onSubmit={handleSimulate} className="card" style={{ padding: 10, marginTop: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--sub)', marginBottom: 6 }}>
            Dev: simulate inbound message
          </div>
          <input placeholder="Linked phone number" required value={simForm.from} onChange={(e) => setSimForm({ ...simForm, from: e.target.value })} style={smallInput} />
          <input placeholder="Message text" required value={simForm.text} onChange={(e) => setSimForm({ ...simForm, text: e.target.value })} style={{ ...smallInput, marginTop: 6 }} />
          <button type="submit" className="btn" style={{ marginTop: 6, width: '100%' }}>Send via mock WhatsApp</button>
        </form>
      </div>

      <div style={{ flex: 1 }}>
        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
        {!detail ? (
          <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>Select a conversation.</div>
        ) : (
          <>
            <div className="card" style={{ padding: 14, marginBottom: 12, maxHeight: 420, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
              {detail.messages.map((m) => (
                <div
                  key={m.id}
                  style={{
                    alignSelf: m.direction === 'inbound' ? 'flex-start' : 'flex-end',
                    background: m.direction === 'inbound' ? 'var(--neutral-bg)' : 'var(--token-bg)',
                    padding: '8px 12px',
                    borderRadius: 10,
                    maxWidth: '70%',
                    fontSize: 13,
                  }}
                >
                  {m.mode && <span className="badge badge-agent" style={{ marginBottom: 4 }}>{m.mode}</span>}
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
                </div>
              ))}
            </div>
            <form onSubmit={handleReply} style={{ display: 'flex', gap: 8 }}>
              <input
                placeholder="Type a manual reply…"
                required
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                style={{ flex: 1, padding: 10, border: '1px solid var(--line)', borderRadius: 8 }}
              />
              <button type="submit" className="btn btn-primary">Send</button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

const smallInput = { padding: 6, border: '1px solid var(--line)', borderRadius: 6, fontSize: 12, width: '100%' }
