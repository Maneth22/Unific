import React, { useEffect, useState } from 'react'
import { generateReport, getMyConversation, initiateRoom, listMyConversations, listReports, sendMyReply } from '../api/clientMeetingRoom'
import { listMyIdentities } from '../api/clientProfiles'

const LANGUAGES = [
  { value: 'auto', label: 'Auto — match their language' },
  { value: 'english', label: 'English' },
  { value: 'hindi', label: 'Hindi' },
  { value: 'tamil', label: 'Tamil' },
  { value: 'sinhala', label: 'Sinhala' },
]
const TONES = ['friendly', 'formal', 'informal']

export default function ClientMeetingRoomPage() {
  const [conversations, setConversations] = useState([])
  const [identities, setIdentities] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [showInitiate, setShowInitiate] = useState(false)
  const [initForm, setInitForm] = useState({
    identity_id: '', target_language: 'auto', tone: 'friendly', character_name: '', character_role: '',
  })
  const [reports, setReports] = useState([])
  const [showReports, setShowReports] = useState(false)
  const [generating, setGenerating] = useState('')
  const [error, setError] = useState('')

  const identityName = (id) => identities.find((i) => i.id === id)?.name || `${id.slice(0, 8)}…`

  async function refresh() {
    const [convs, ids] = await Promise.all([listMyConversations(), listMyIdentities()])
    setConversations(convs)
    setIdentities(ids)
  }

  useEffect(() => { refresh() }, [])

  useEffect(() => {
    if (selectedId) {
      getMyConversation(selectedId).then(setDetail)
      listReports(selectedId).then(setReports)
      setShowReports(false)
    }
  }, [selectedId])

  async function handleInitiate(e) {
    e.preventDefault()
    setError('')
    try {
      const conv = await initiateRoom(initForm)
      setShowInitiate(false)
      await refresh()
      setSelectedId(conv.id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start the comms room')
    }
  }

  async function handleReply(e) {
    e.preventDefault()
    setError('')
    setSending(true)
    try {
      await sendMyReply(selectedId, replyText)
      setReplyText('')
      setDetail(await getMyConversation(selectedId))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send message')
    } finally {
      setSending(false)
    }
  }

  async function handleGenerateReport(reportType) {
    setError('')
    setGenerating(reportType)
    try {
      await generateReport(selectedId, reportType)
      setReports(await listReports(selectedId))
      setShowReports(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Report generation failed — try again')
    } finally {
      setGenerating('')
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>Meeting Room</h1>
          <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
            You write in English — they read their own language. They write in their language —
            you read clear English. The agent handles everything in between.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowInitiate(!showInitiate)}>
          {showInitiate ? 'Cancel' : '+ Start a comms room'}
        </button>
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}

      {showInitiate && (
        <form onSubmit={handleInitiate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 10, gridTemplateColumns: '1fr 1fr' }}>
          <div style={{ gridColumn: '1 / -1', fontWeight: 700, fontSize: 13 }}>
            Set up the agent before the conversation starts
          </div>
          <div>
            <div style={labelStyle}>Who is this room with?</div>
            <select required value={initForm.identity_id} onChange={(e) => setInitForm({ ...initForm, identity_id: e.target.value })} style={inputStyle}>
              <option value="">— select —</option>
              {identities.map((i) => <option key={i.id} value={i.id}>{i.name} ({i.id_type})</option>)}
            </select>
          </div>
          <div>
            <div style={labelStyle}>Their language</div>
            <select value={initForm.target_language} onChange={(e) => setInitForm({ ...initForm, target_language: e.target.value })} style={inputStyle}>
              {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </select>
          </div>
          <div>
            <div style={labelStyle}>Tone</div>
            <select value={initForm.tone} onChange={(e) => setInitForm({ ...initForm, tone: e.target.value })} style={inputStyle}>
              {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={labelStyle}>Character name (e.g. Jake)</div>
            <input value={initForm.character_name} onChange={(e) => setInitForm({ ...initForm, character_name: e.target.value })} style={inputStyle} placeholder="Jake" />
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={labelStyle}>Character role (e.g. a student, a community service worker)</div>
            <input value={initForm.character_role} onChange={(e) => setInitForm({ ...initForm, character_role: e.target.value })} style={inputStyle} placeholder="a community service worker" />
          </div>
          <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Start room</button>
        </form>
      )}

      <div style={{ display: 'flex', gap: 16 }}>
        <div className="card" style={{ width: 250, padding: 12, flexShrink: 0 }}>
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => setSelectedId(c.id)}
              style={{
                padding: 8, borderRadius: 6, cursor: 'pointer', fontSize: 12,
                background: selectedId === c.id ? 'var(--slate-bg)' : 'transparent',
              }}
            >
              <div style={{ fontWeight: 700 }}>{identityName(c.identity_id)}</div>
              <div style={{ color: 'var(--sub)' }}>
                {c.target_language}{c.character_name ? ` · ${c.character_name}` : ''} · {c.tone || 'default'}
              </div>
            </div>
          ))}
          {conversations.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 12 }}>No rooms yet — start one above.</div>}
        </div>

        <div style={{ flex: 1 }}>
          {!detail ? (
            <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>Select a comms room.</div>
          ) : (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 13 }}>
                  <strong>{identityName(detail.identity_id)}</strong>{' '}
                  <span className="badge badge-id">{detail.target_language}</span>{' '}
                  {detail.character_name && (
                    <span className="badge badge-agent">{detail.character_name}{detail.character_role ? `, ${detail.character_role}` : ''}</span>
                  )}{' '}
                  <span className="badge badge-room">{detail.tone || 'default tone'}</span>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn" disabled={!!generating} onClick={() => handleGenerateReport('session_summary')}>
                    {generating === 'session_summary' ? 'Generating…' : 'Summary report'}
                  </button>
                  <button className="btn" disabled={!!generating} onClick={() => handleGenerateReport('satisfaction_analysis')}>
                    {generating === 'satisfaction_analysis' ? 'Analyzing…' : 'Satisfaction analysis'}
                  </button>
                  {reports.length > 0 && (
                    <button className="btn" onClick={() => setShowReports(!showReports)}>
                      Reports ({reports.length})
                    </button>
                  )}
                </div>
              </div>

              {showReports && <ReportsPanel reports={reports} />}

              <div className="card" style={{ padding: 14, marginBottom: 12, maxHeight: 420, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {detail.messages.map((m) => <MessageBubble key={m.id} m={m} />)}
                {detail.messages.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No messages yet.</div>}
              </div>

              <form onSubmit={handleReply} style={{ display: 'flex', gap: 8 }}>
                <input
                  placeholder="Write in English — it will be sent in their language…"
                  required
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  style={{ flex: 1, padding: 10, border: '1px solid var(--line)', borderRadius: 8 }}
                />
                <button type="submit" className="btn btn-primary" disabled={sending}>
                  {sending ? 'Translating…' : 'Send'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ m }) {
  const inbound = m.direction === 'inbound'
  const tone = m.tone_analysis || {}
  return (
    <div
      style={{
        alignSelf: inbound ? 'flex-start' : 'flex-end',
        background: inbound ? 'var(--neutral-bg)' : 'var(--token-bg)',
        padding: '9px 12px',
        borderRadius: 10,
        maxWidth: '75%',
        fontSize: 13,
      }}
    >
      {inbound ? (
        <>
          <div>{m.translated_text || m.original_text}</div>
          {m.translated_text && m.original_text !== m.translated_text && (
            <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>
              Original{m.detected_language ? ` (${m.detected_language})` : ''}: {m.original_text}
            </div>
          )}
          {tone.brief_insight && (
            <div style={{ fontSize: 11, marginTop: 6 }}>
              {tone.emotional_tone && <span className="badge badge-pending" style={{ marginRight: 4 }}>{tone.emotional_tone}</span>}
              <span style={{ color: 'var(--sub)' }}>{tone.brief_insight}</span>
            </div>
          )}
        </>
      ) : (
        <>
          <div>{m.original_text}</div>
          {m.translated_text && m.translated_text !== m.original_text && (
            <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>Sent as: {m.translated_text}</div>
          )}
          {(m.key_points || []).length > 0 && (
            <div style={{ marginTop: 5 }}>
              {m.key_points.map((k) => <span key={k} className="badge badge-room" style={{ marginRight: 4, fontSize: 10 }}>{k}</span>)}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ReportsPanel({ reports }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
      {reports.map((r) => (
        <div key={r.id} className="card" style={{ padding: 14, fontSize: 13 }}>
          <div style={{ marginBottom: 8 }}>
            <span className={`badge ${r.report_type === 'session_summary' ? 'badge-id' : 'badge-agent'}`}>
              {r.report_type === 'session_summary' ? 'Session summary' : 'Satisfaction analysis'}
            </span>{' '}
            <span style={{ color: 'var(--sub)', fontSize: 11 }}>
              {new Date(r.created_at).toLocaleString()} · {r.message_count} messages
            </span>
          </div>
          {r.report_type === 'session_summary' ? <SummaryReport c={r.content} /> : <SatisfactionReport c={r.content} />}
        </div>
      ))}
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div style={{ display: 'flex', gap: 8, padding: '3px 0', fontSize: 12 }}>
      <span style={{ color: 'var(--sub)', minWidth: 130, flexShrink: 0 }}>{label}</span>
      <span>{children}</span>
    </div>
  )
}

function SummaryReport({ c }) {
  return (
    <div>
      <p style={{ marginTop: 0 }}>{c.summary}</p>
      <Row label="Community needs">{c.community_needs}</Row>
      <Row label="Client offers">{c.client_offers}</Row>
      <Row label="Gaps">{c.gaps}</Row>
      <Row label="Sentiment"><span className="badge badge-pending">{c.sentiment}</span> comfort: {c.comfort_level} · requirements met: {c.requirements_met}</Row>
      <Row label="Profile">{c.communication_style} · {c.language_proficiency} · {c.overall_demeanor}</Row>
    </div>
  )
}

function SatisfactionReport({ c }) {
  return (
    <div>
      <p style={{ marginTop: 0 }}>
        <span className={`badge ${c.satisfaction_level === 'high' ? 'badge-agent' : c.satisfaction_level === 'low' ? 'badge-alert' : 'badge-pending'}`}>
          {c.satisfaction_level} — {c.satisfaction_score}/10
        </span>{' '}
        <span className="badge badge-room">trend: {c.sentiment_trend}</span>
      </p>
      <p>{c.summary}</p>
      {(c.positives || []).length > 0 && <Row label="What worked">{c.positives.join(' · ')}</Row>}
      {(c.concerns || []).length > 0 && <Row label="Concerns">{c.concerns.join(' · ')}</Row>}
      {(c.unmet_needs || []).length > 0 && <Row label="Unmet needs">{c.unmet_needs.join(' · ')}</Row>}
      {(c.recommendations || []).length > 0 && <Row label="Recommendations">{c.recommendations.join(' · ')}</Row>}
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8, width: '100%', fontSize: 13 }
const labelStyle = { fontSize: 11, color: 'var(--sub)', marginBottom: 3, fontWeight: 700 }
