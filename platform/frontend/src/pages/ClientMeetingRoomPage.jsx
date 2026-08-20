import React, { useEffect, useState } from 'react'
import {
  addMyParticipant, endMyMeeting, generateReport, getMyConversation, getMyMeeting, getMyMeetingChat, initiateRoom,
  joinMyMeeting, listMyConversations, listMyMeetings, listReports, retryMyMeetingTranslation, scheduleMyMeeting,
  sendMyReply,
} from '../api/clientMeetingRoom'
import { getTranslationLanguages } from '../api/meetingRoom'
import { listMyIdentities } from '../api/clientProfiles'
import VideoCallRoom from '../components/VideoCallRoom'
import { LANGUAGE_LABELS } from '../components/video-call/callConstants'

// Mirrors the backend's schemas.MAX_TRANSLATE_LANGUAGES — client-side is
// just a UX affordance; the server validator is the actual source of truth.
const MAX_TRANSLATE_LANGUAGES = 3

const LANGUAGES = [
  { value: 'auto', label: 'Auto — match their language' },
  { value: 'english', label: 'English' },
  { value: 'hindi', label: 'Hindi' },
  { value: 'tamil', label: 'Tamil' },
  { value: 'sinhala', label: 'Sinhala' },
]
const TONES = ['friendly', 'formal', 'informal']

const TABS = [
  { key: 'chat', label: 'Chat' },
  { key: 'meetings', label: 'Meetings' },
]

export default function ClientMeetingRoomPage() {
  const [tab, setTab] = useState('chat')

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--line)', marginBottom: 20, overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              border: 'none',
              background: 'none',
              padding: '10px 14px',
              fontSize: 13,
              fontWeight: 700,
              cursor: 'pointer',
              color: tab === t.key ? 'var(--token)' : 'var(--sub)',
              borderBottom: tab === t.key ? '2px solid var(--token)' : '2px solid transparent',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'chat' ? <ChatTab /> : <MeetingsTab />}
    </div>
  )
}

const MEETING_STATUS_BADGE = {
  scheduled: 'badge-pending',
  live: 'badge-agent',
  completed: 'badge-room',
  cancelled: 'badge-alert',
}

const meetingRtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

function meetingRelativeTime(iso) {
  const diffMs = new Date(iso) - Date.now()
  const abs = Math.abs(diffMs)
  const minute = 60000, hour = 3600000, day = 86400000
  if (abs < hour) return meetingRtf.format(Math.round(diffMs / minute), 'minute')
  if (abs < day) return meetingRtf.format(Math.round(diffMs / hour), 'hour')
  return meetingRtf.format(Math.round(diffMs / day), 'day')
}

const EMPTY_MEETING_FORM = {
  host_identity_id: '', scheduled_at: '', translate_live: true, translate_languages: ['en'], notes: '',
  participant_identity_ids: [],
}

function MeetingsTab() {
  const [meetings, setMeetings] = useState([])
  const [identities, setIdentities] = useState([])
  const [call, setCall] = useState(null)
  const [error, setError] = useState('')
  const [joiningId, setJoiningId] = useState('')
  const [pending, setPending] = useState({}) // { [meetingId]: 'end' }
  const [showSchedule, setShowSchedule] = useState(false)
  const [form, setForm] = useState(EMPTY_MEETING_FORM)
  const [scheduling, setScheduling] = useState(false)
  const [success, setSuccess] = useState('')
  // Named distinctly from the unrelated LANGUAGES constant above (that one
  // is the WhatsApp comms target_language picker, full-word values) —
  // these are the live-translation codes ('en'/'si'/'hi').
  const [selectableTranslateLanguages, setSelectableTranslateLanguages] = useState(['en'])
  // Expand/detail view — participants, invite links, and "add participant"
  // for one meeting at a time, mirroring the staff scheduler's own pattern.
  const [expandedId, setExpandedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [copiedId, setCopiedId] = useState('')
  const [addIdentityId, setAddIdentityId] = useState('')
  const [addingParticipant, setAddingParticipant] = useState(false)
  const [addParticipantError, setAddParticipantError] = useState('')

  const identityName = (id) => identities.find((i) => i.id === id)?.name || `${id.slice(0, 8)}…`

  async function refresh() {
    const [ms, ids] = await Promise.all([listMyMeetings(), listMyIdentities()])
    setMeetings(ms)
    setIdentities(ids)
  }

  useEffect(() => { refresh() }, [])
  useEffect(() => { getTranslationLanguages().then(setSelectableTranslateLanguages).catch(() => {}) }, [])

  // So a meeting flips to "live" (or someone else's join shows up) without
  // the client having to manually refresh the page.
  useEffect(() => {
    if (call) return
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [call])

  function toggleParticipant(id) {
    setForm((f) => ({
      ...f,
      participant_identity_ids: f.participant_identity_ids.includes(id)
        ? f.participant_identity_ids.filter((x) => x !== id)
        : [...f.participant_identity_ids, id],
    }))
  }

  // 'en' is always included and not toggleable — the server force-includes
  // it too, this just keeps the UI honest about that.
  function toggleTranslateLanguage(code) {
    if (code === 'en') return
    setForm((f) => {
      if (f.translate_languages.includes(code)) {
        return { ...f, translate_languages: f.translate_languages.filter((x) => x !== code) }
      }
      if (f.translate_languages.length >= MAX_TRANSLATE_LANGUAGES) return f
      return { ...f, translate_languages: [...f.translate_languages, code] }
    })
  }

  async function handleSchedule(e) {
    e.preventDefault()
    setError('')
    setSuccess('')
    setScheduling(true)
    try {
      await scheduleMyMeeting({ ...form, scheduled_at: new Date(form.scheduled_at).toISOString() })
      setForm(EMPTY_MEETING_FORM)
      setShowSchedule(false)
      setSuccess('Meeting scheduled — its LiveKit room is ready now.')
      setTimeout(() => setSuccess(''), 4000)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not schedule meeting')
    } finally {
      setScheduling(false)
    }
  }

  async function handleJoin(meetingId) {
    setError('')
    setJoiningId(meetingId)
    try {
      const join = await joinMyMeeting(meetingId)
      setCall(join)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not join meeting')
    } finally {
      setJoiningId('')
    }
  }

  async function handleEnd(meetingId) {
    setError('')
    setPending((p) => ({ ...p, [meetingId]: 'end' }))
    try {
      await endMyMeeting(meetingId)
      setCall(null)
      await refresh()
      if (expandedId === meetingId) setDetail(await getMyMeeting(meetingId))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not end meeting')
    } finally {
      setPending((p) => { const n = { ...p }; delete n[meetingId]; return n })
    }
  }

  async function toggleExpand(meeting) {
    setAddIdentityId('')
    setAddParticipantError('')
    if (expandedId === meeting.id) {
      setExpandedId('')
      setDetail(null)
      return
    }
    setExpandedId(meeting.id)
    setDetail(await getMyMeeting(meeting.id))
  }

  async function handleCopyInvite(key, url) {
    await navigator.clipboard.writeText(url)
    setCopiedId(key)
    setTimeout(() => setCopiedId(''), 1500)
  }

  async function handleAddParticipant(meetingId) {
    setAddParticipantError('')
    setAddingParticipant(true)
    try {
      await addMyParticipant(meetingId, addIdentityId)
      setAddIdentityId('')
      setDetail(await getMyMeeting(meetingId))
    } catch (err) {
      setAddParticipantError(err.response?.data?.detail || 'Could not add participant')
    } finally {
      setAddingParticipant(false)
    }
  }

  if (call) {
    return (
      <div>
        <button className="btn" style={{ marginBottom: 12 }} onClick={() => setCall(null)}>&larr; Leave call</button>
        <VideoCallRoom
          serverUrl={call.livekit_url}
          token={call.token}
          languages={call.languages}
          openInviteUrl={call.open_invite_url}
          onDisconnected={() => setCall(null)}
          fetchChatHistory={() => getMyMeetingChat(call.meeting_id)}
          viewerRole="host"
          onRetryTranslation={() => retryMyMeetingTranslation(call.meeting_id)}
        />
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <p style={{ color: 'var(--sub)', margin: 0 }}>
          Schedule a video meeting with your own community — a LiveKit room is created immediately.
        </p>
        <button className="btn btn-primary" onClick={() => setShowSchedule(!showSchedule)}>
          {showSchedule ? 'Cancel' : '+ Schedule meeting'}
        </button>
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}
      {success && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{success}</div>}

      {showSchedule && (
        <form onSubmit={handleSchedule} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
          <select required value={form.host_identity_id} onChange={(e) => setForm({ ...form, host_identity_id: e.target.value })} style={inputStyle}>
            <option value="">— who is this meeting with? —</option>
            {identities.map((i) => <option key={i.id} value={i.id}>{i.name} ({i.id_type})</option>)}
          </select>
          <input
            type="datetime-local" required value={form.scheduled_at}
            onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })}
            style={inputStyle}
          />
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 4 }}>
              Other members to invite
              {form.participant_identity_ids.length > 0 && (
                <span className="badge badge-account" style={{ marginLeft: 6 }}>{form.participant_identity_ids.length} selected</span>
              )}
            </div>
            <div style={{ border: '1px solid var(--line)', borderRadius: 8, maxHeight: 150, overflowY: 'auto' }}>
              {identities.filter((i) => i.id !== form.host_identity_id).map((i) => {
                const checked = form.participant_identity_ids.includes(i.id)
                return (
                  <label
                    key={i.id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', fontSize: 13, cursor: 'pointer',
                      background: checked ? 'var(--token-bg)' : 'transparent',
                      borderBottom: '1px solid var(--line)',
                    }}
                  >
                    <input type="checkbox" checked={checked} onChange={() => toggleParticipant(i.id)} />
                    {i.name}
                  </label>
                )
              })}
              {identities.length === 0 && <div style={{ padding: 10, color: 'var(--sub)', fontSize: 12 }}>No community members yet.</div>}
            </div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <input type="checkbox" checked={form.translate_live} onChange={(e) => setForm({ ...form, translate_live: e.target.checked })} />
            Translate live
          </label>

          {form.translate_live && (
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 4 }}>
                Translation languages
                <span style={{ marginLeft: 6, fontSize: 11 }}>(up to {MAX_TRANSLATE_LANGUAGES}, English always included)</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, opacity: 0.7 }}>
                  <input type="checkbox" checked disabled />
                  {LANGUAGE_LABELS.en}
                </label>
                {selectableTranslateLanguages.filter((code) => code !== 'en').map((code) => {
                  const checked = form.translate_languages.includes(code)
                  const disabled = !checked && form.translate_languages.length >= MAX_TRANSLATE_LANGUAGES
                  return (
                    <label key={code} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, opacity: disabled ? 0.5 : 1 }}>
                      <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggleTranslateLanguage(code)} />
                      {LANGUAGE_LABELS[code] || code}
                    </label>
                  )
                })}
              </div>
            </div>
          )}

          <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} style={inputStyle} />
          <button type="submit" className="btn btn-primary" disabled={scheduling} style={{ gridColumn: '1 / -1' }}>
            {scheduling ? 'Scheduling…' : 'Schedule'}
          </button>
        </form>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {meetings.map((m) => (
          <div key={m.id} className="card" style={{ padding: 14 }}>
            <div
              className="card-clickable"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
              onClick={() => toggleExpand(m)}
            >
              <div>
                <span className={`badge ${MEETING_STATUS_BADGE[m.status] || 'badge-room'} ${m.status === 'live' ? 'badge-pulse' : ''}`}>
                  {m.status}
                </span>{' '}
                {m.host_identity_id && <strong style={{ fontSize: 13 }}>{identityName(m.host_identity_id)}</strong>}{' '}
                <span style={{ fontSize: 12, color: 'var(--sub)' }}>{new Date(m.scheduled_at).toLocaleString()}</span>
                <span style={{ fontSize: 11, color: 'var(--sub)', marginLeft: 6 }}>({meetingRelativeTime(m.scheduled_at)})</span>
                {m.notes && <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 4 }}>{m.notes}</div>}
              </div>
              <div style={{ display: 'flex', gap: 6 }} onClick={(e) => e.stopPropagation()}>
                {(m.status === 'scheduled' || m.status === 'live') && (
                  <button className="btn btn-primary" disabled={joiningId === m.id} onClick={() => handleJoin(m.id)}>
                    {joiningId === m.id ? 'Joining…' : 'Join'}
                  </button>
                )}
                {m.status === 'live' && (
                  <button className="btn" disabled={!!pending[m.id]} onClick={() => handleEnd(m.id)}>
                    {pending[m.id] === 'end' ? 'Closing…' : 'Close room'}
                  </button>
                )}
              </div>
            </div>

            {expandedId === m.id && detail && (
              <div style={{ marginTop: 12, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
                {detail.open_invite_url && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 12 }}>
                    <span style={{ color: 'var(--sub)' }}>Shareable link — anyone who opens it can join:</span>
                    <button
                      onClick={() => handleCopyInvite('open', detail.open_invite_url)}
                      style={{
                        border: 'none', background: 'none', cursor: 'pointer', fontSize: 11, padding: 0,
                        color: copiedId === 'open' ? 'var(--green)' : 'var(--token)', fontWeight: copiedId === 'open' ? 700 : 400,
                      }}
                    >
                      {copiedId === 'open' ? '✓ copied' : 'copy link'}
                    </button>
                  </div>
                )}

                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Participants</div>
                {detail.participants.map((p) => (
                  <div key={p.id} style={{ fontSize: 12, marginBottom: 4, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <span>
                      {p.identity_id ? identityName(p.identity_id) : p.guest_name || 'Staff'}
                      {p.guest_name && <span className="badge badge-account" style={{ marginLeft: 6, fontSize: 10 }}>guest</span>}
                      {p.joined_at && <span className="badge badge-agent" style={{ marginLeft: 6, fontSize: 10 }}>joined</span>}
                    </span>
                    {detail.invite_urls[p.id] && (
                      <button
                        onClick={() => handleCopyInvite(p.id, detail.invite_urls[p.id])}
                        style={{
                          border: 'none', background: 'none', cursor: 'pointer', fontSize: 11, padding: 0,
                          color: copiedId === p.id ? 'var(--green)' : 'var(--token)', fontWeight: copiedId === p.id ? 700 : 400,
                        }}
                      >
                        {copiedId === p.id ? '✓ copied' : 'copy invite link'}
                      </button>
                    )}
                  </div>
                ))}

                <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Add participant</div>
                  {addParticipantError && (
                    <div className="badge badge-alert" style={{ display: 'block', marginBottom: 6, padding: '6px 10px', fontSize: 11 }}>
                      {addParticipantError}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <select
                      value={addIdentityId}
                      onChange={(e) => setAddIdentityId(e.target.value)}
                      style={{ ...inputStyle, width: 'auto', flex: 1, minWidth: 160 }}
                    >
                      <option value="">— community member —</option>
                      {identities
                        .filter((i) => !detail.participants.some((p) => p.identity_id === i.id))
                        .map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
                    </select>
                    <button
                      className="btn btn-primary"
                      disabled={!addIdentityId || addingParticipant}
                      onClick={() => handleAddParticipant(m.id)}
                    >
                      {addingParticipant ? 'Adding…' : 'Add'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
        {meetings.length === 0 && <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>No meetings scheduled.</div>}
      </div>
    </div>
  )
}

function ChatTab() {
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
