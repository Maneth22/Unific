import React, { useEffect, useRef, useState } from 'react'
import { createMeeting, deleteMeeting, endMeeting, getMeeting, joinMeeting, listMeetings } from '../../api/meetingRoom'
import { listIdentities, listClientOrgIdentities } from '../../api/profiles'
import { listStaffLite } from '../../api/staffDirectory'
import VideoCallRoom from '../../components/VideoCallRoom'

const EMPTY_FORM = {
  host_identity_id: '', scheduled_at: '', translate_live: true, notes: '',
  participant_identity_ids: [], staff_participant_ids: [],
}

const STATUS_BADGE = {
  scheduled: 'badge-pending',
  live: 'badge-agent',
  completed: 'badge-room',
  cancelled: 'badge-alert',
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

function relativeTime(iso) {
  const diffMs = new Date(iso) - Date.now()
  const abs = Math.abs(diffMs)
  const minute = 60000, hour = 3600000, day = 86400000
  if (abs < hour) return rtf.format(Math.round(diffMs / minute), 'minute')
  if (abs < day) return rtf.format(Math.round(diffMs / hour), 'hour')
  return rtf.format(Math.round(diffMs / day), 'day')
}

export default function MeetingScheduler() {
  const [meetings, setMeetings] = useState([])
  const [identities, setIdentities] = useState([]) // full tree — only used to resolve names for display
  const [clientOrgs, setClientOrgs] = useState([]) // org-root identities only — the "meet with a client" picker
  const [staffList, setStaffList] = useState([])
  // "staff" — internal meeting, no identity involved at all. "client_org" —
  // the admin meeting a client organization's owner/co-owners; per spec the
  // admin never meets the ILC/community groups linked to a client directly,
  // so this picker is restricted to org-root identities, never the full tree.
  const [mode, setMode] = useState('staff')
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [expandedId, setExpandedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [call, setCall] = useState(null) // { livekit_url, token } while actively joined
  const [pending, setPending] = useState({}) // { [meetingId]: 'join' | 'end' | 'delete' }
  const [copiedId, setCopiedId] = useState('')
  const callActive = useRef(false)

  const identityName = (id) => (id ? identities.find((i) => i.id === id)?.name || `${id.slice(0, 8)}…` : 'Staff meeting')

  async function refresh() {
    const [ms, ids, orgs, staff] = await Promise.all([
      listMeetings(), listIdentities(), listClientOrgIdentities(), listStaffLite(),
    ])
    setMeetings(ms)
    setIdentities(ids)
    setClientOrgs(orgs)
    setStaffList(staff)
  }

  async function refreshMeetingsOnly() {
    setMeetings(await listMeetings())
    if (expandedId) {
      getMeeting(expandedId).then(setDetail).catch(() => {})
    }
  }

  useEffect(() => { refresh() }, [])

  // Keeps the list (and any expanded meeting's participant/join state) in
  // sync without a manual refresh — e.g. so a meeting flips to "live" the
  // moment someone else joins, and the join UI stops offering a stale action.
  useEffect(() => {
    callActive.current = !!call
    const id = setInterval(() => { if (!callActive.current) refreshMeetingsOnly() }, 5000)
    return () => clearInterval(id)
  }, [expandedId, call])

  function toggleParticipantIdentity(id) {
    setForm((f) => ({
      ...f,
      participant_identity_ids: f.participant_identity_ids.includes(id)
        ? f.participant_identity_ids.filter((x) => x !== id)
        : [...f.participant_identity_ids, id],
    }))
  }

  function toggleParticipantStaff(id) {
    setForm((f) => ({
      ...f,
      staff_participant_ids: f.staff_participant_ids.includes(id)
        ? f.staff_participant_ids.filter((x) => x !== id)
        : [...f.staff_participant_ids, id],
    }))
  }

  function switchMode(next) {
    setMode(next)
    setForm(EMPTY_FORM)
  }

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    setSuccess('')
    // "staff" meetings have no identity-tree host at all; "client_org"
    // meetings never carry identity participants outside the client-org
    // picker (never an ILC/community identity — enforced server-side too).
    const payload = mode === 'staff'
      ? { ...form, host_identity_id: null, participant_identity_ids: [], meeting_kind: 'staff' }
      : { ...form, meeting_kind: 'client_org' }
    try {
      await createMeeting({ ...payload, scheduled_at: new Date(form.scheduled_at).toISOString() })
      setForm(EMPTY_FORM)
      setSuccess('Meeting scheduled — its LiveKit room is ready now.')
      setTimeout(() => setSuccess(''), 4000)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not schedule meeting')
    }
  }

  async function toggleExpand(meeting) {
    if (expandedId === meeting.id) {
      setExpandedId('')
      setDetail(null)
      return
    }
    setExpandedId(meeting.id)
    setDetail(await getMeeting(meeting.id))
  }

  async function handleJoin(meetingId) {
    setError('')
    setPending((p) => ({ ...p, [meetingId]: 'join' }))
    try {
      const join = await joinMeeting(meetingId)
      setCall(join)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not join meeting')
    } finally {
      setPending((p) => { const n = { ...p }; delete n[meetingId]; return n })
    }
  }

  async function handleEnd(meetingId) {
    setError('')
    setPending((p) => ({ ...p, [meetingId]: 'end' }))
    try {
      await endMeeting(meetingId)
      setCall(null)
      await refresh()
      if (expandedId === meetingId) setDetail(await getMeeting(meetingId))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not end meeting')
    } finally {
      setPending((p) => { const n = { ...p }; delete n[meetingId]; return n })
    }
  }

  async function handleDelete(meetingId) {
    if (!window.confirm('Delete this meeting? This closes its video room on LiveKit and cannot be undone.')) return
    setError('')
    setPending((p) => ({ ...p, [meetingId]: 'delete' }))
    try {
      await deleteMeeting(meetingId)
      setCall(null)
      if (expandedId === meetingId) {
        setExpandedId('')
        setDetail(null)
      }
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not delete meeting')
      setPending((p) => { const n = { ...p }; delete n[meetingId]; return n })
    }
  }

  async function handleCopyInvite(participantId, url) {
    await navigator.clipboard.writeText(url)
    setCopiedId(participantId)
    setTimeout(() => setCopiedId(''), 1500)
  }

  if (call) {
    return (
      <div>
        <button className="btn" style={{ marginBottom: 12 }} onClick={() => setCall(null)}>&larr; Leave call</button>
        <VideoCallRoom serverUrl={call.livekit_url} token={call.token} onDisconnected={() => setCall(null)} />
      </div>
    )
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Schedule a video meeting — a LiveKit room is created immediately. Meet with your own
        staff, or with a client organization (never their ILC/community groups directly).
        Scheduling here also submits timing to the one master calendar in the Accounts Room.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}
      {success && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{success}</div>}

      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        <button type="button" className={mode === 'staff' ? 'btn btn-primary' : 'btn'} onClick={() => switchMode('staff')}>
          Meet with staff
        </button>
        <button type="button" className={mode === 'client_org' ? 'btn btn-primary' : 'btn'} onClick={() => switchMode('client_org')}>
          Meet with a client
        </button>
      </div>

      <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
        {mode === 'client_org' && (
          <select required value={form.host_identity_id} onChange={(e) => setForm({ ...form, host_identity_id: e.target.value })} style={inputStyle}>
            <option value="">— client organization —</option>
            {clientOrgs.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        )}
        <input
          type="datetime-local" required value={form.scheduled_at}
          onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })}
          style={{ ...inputStyle, gridColumn: mode === 'client_org' ? 'auto' : '1 / -1' }}
        />

        {mode === 'client_org' ? (
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 4 }}>
              Other client organizations
              {form.participant_identity_ids.length > 0 && (
                <span className="badge badge-account" style={{ marginLeft: 6 }}>{form.participant_identity_ids.length} selected</span>
              )}
            </div>
            <div style={{ border: '1px solid var(--line)', borderRadius: 8, maxHeight: 150, overflowY: 'auto' }}>
              {clientOrgs.filter((i) => i.id !== form.host_identity_id).map((i) => {
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
                    <input type="checkbox" checked={checked} onChange={() => toggleParticipantIdentity(i.id)} />
                    {i.name}
                  </label>
                )
              })}
              {clientOrgs.length === 0 && <div style={{ padding: 10, color: 'var(--sub)', fontSize: 12 }}>No client organizations yet.</div>}
            </div>
          </div>
        ) : (
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 4 }}>
              Staff to invite
              {form.staff_participant_ids.length > 0 && (
                <span className="badge badge-account" style={{ marginLeft: 6 }}>{form.staff_participant_ids.length} selected</span>
              )}
            </div>
            <div style={{ border: '1px solid var(--line)', borderRadius: 8, maxHeight: 150, overflowY: 'auto' }}>
              {staffList.map((s) => {
                const checked = form.staff_participant_ids.includes(s.id)
                return (
                  <label
                    key={s.id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', fontSize: 13, cursor: 'pointer',
                      background: checked ? 'var(--token-bg)' : 'transparent',
                      borderBottom: '1px solid var(--line)',
                    }}
                  >
                    <input type="checkbox" checked={checked} onChange={() => toggleParticipantStaff(s.id)} />
                    {s.full_name}
                  </label>
                )
              })}
              {staffList.length === 0 && <div style={{ padding: 10, color: 'var(--sub)', fontSize: 12 }}>No other staff yet.</div>}
            </div>
            <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>
              Selected staff get this meeting link in their inbox.
            </div>
          </div>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={form.translate_live} onChange={(e) => setForm({ ...form, translate_live: e.target.checked })} />
          Translate live
        </label>
        <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} style={inputStyle} />
        <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Schedule</button>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {meetings.map((m) => {
          const participantCount = expandedId === m.id && detail ? detail.participants.length : null
          return (
            <div key={m.id} className="card" style={{ padding: 12 }}>
              <div
                className="card-clickable"
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderRadius: 6, padding: '2px 4px', margin: '-2px -4px' }}
                onClick={() => toggleExpand(m)}
              >
                <div>
                  <span className={`badge ${STATUS_BADGE[m.status] || 'badge-room'} ${m.status === 'live' ? 'badge-pulse' : ''}`}>
                    {m.status}
                  </span>{' '}
                  <strong>{identityName(m.host_identity_id)}</strong>
                  {participantCount !== null && (
                    <span style={{ fontSize: 12, color: 'var(--sub)', marginLeft: 6 }}>· {participantCount} participants</span>
                  )}
                  {m.notes && <div style={{ fontSize: 12, color: 'var(--sub)' }}>{m.notes}</div>}
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 12, color: 'var(--sub)' }}>{new Date(m.scheduled_at).toLocaleString()}</div>
                  <div style={{ fontSize: 11, color: 'var(--sub)' }}>{relativeTime(m.scheduled_at)}</div>
                </div>
              </div>

              {expandedId === m.id && detail && (
                <div style={{ marginTop: 12, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    {(m.status === 'scheduled' || m.status === 'live') && (
                      <button className="btn btn-primary" disabled={!!pending[m.id]} onClick={() => handleJoin(m.id)}>
                        {pending[m.id] === 'join' ? 'Joining…' : 'Join'}
                      </button>
                    )}
                    {m.status === 'live' && (
                      <button className="btn" disabled={!!pending[m.id]} onClick={() => handleEnd(m.id)}>
                        {pending[m.id] === 'end' ? 'Closing…' : 'Close room'}
                      </button>
                    )}
                    {(m.status === 'completed' || m.status === 'cancelled') && (
                      <span style={{ fontSize: 12, color: 'var(--sub)' }}>This meeting has ended.</span>
                    )}
                    <button
                      className="btn btn-danger"
                      disabled={!!pending[m.id]}
                      style={{ marginLeft: 'auto' }}
                      onClick={() => handleDelete(m.id)}
                    >
                      {pending[m.id] === 'delete' ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--sub)', marginBottom: 10 }}>
                    "Close room" ends the live call but keeps the record. "Delete" force-closes the
                    LiveKit room (if still open) and removes the meeting entirely.
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Participants</div>
                  {detail.participants.map((p) => (
                    <div key={p.id} style={{ fontSize: 12, marginBottom: 4, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span>
                        {p.identity_id
                          ? identityName(p.identity_id)
                          : staffList.find((s) => s.id === p.staff_user_id)?.full_name || 'Staff'}
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
                </div>
              )}
            </div>
          )
        })}
        {meetings.length === 0 && <div style={{ color: 'var(--sub)' }}>No meetings scheduled.</div>}
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
