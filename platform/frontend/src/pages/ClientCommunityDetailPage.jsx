import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { generateReport, listReports } from '../api/clientMeetingRoom'
import { addRosterNumbers, listCommunityMembers, listRoster } from '../api/clientProfiles'

export default function ClientCommunityDetailPage() {
  const { groupId } = useParams()
  const [members, setMembers] = useState([])
  const [roster, setRoster] = useState([])
  const [rosterInput, setRosterInput] = useState('')
  const [showRoster, setShowRoster] = useState(false)
  const [error, setError] = useState('')
  const [rosterError, setRosterError] = useState('')
  const [addingRoster, setAddingRoster] = useState(false)
  const [expandedId, setExpandedId] = useState('')
  const [reportsByMember, setReportsByMember] = useState({})
  const [generatingId, setGeneratingId] = useState('')

  async function refresh() {
    const [m, r] = await Promise.all([listCommunityMembers(groupId), listRoster(groupId)])
    setMembers(m)
    setRoster(r)
  }

  useEffect(() => { refresh() }, [groupId])

  async function handleAddRoster(e) {
    e.preventDefault()
    setRosterError('')
    setAddingRoster(true)
    try {
      const numbers = rosterInput.split(/[\s,]+/).map((n) => n.trim()).filter(Boolean)
      await addRosterNumbers(groupId, numbers)
      setRosterInput('')
      await refresh()
    } catch (err) {
      setRosterError(err.response?.data?.detail || 'Could not add roster numbers')
    } finally {
      setAddingRoster(false)
    }
  }

  async function toggleExpand(member) {
    if (expandedId === member.id) {
      setExpandedId('')
      return
    }
    setExpandedId(member.id)
    if (member.conversation_id && !reportsByMember[member.id]) {
      const reports = await listReports(member.conversation_id)
      setReportsByMember((prev) => ({ ...prev, [member.id]: reports }))
    }
  }

  async function handleGenerateSummary(member) {
    setError('')
    setGeneratingId(member.id)
    try {
      await generateReport(member.conversation_id, 'member_summary')
      const reports = await listReports(member.conversation_id)
      setReportsByMember((prev) => ({ ...prev, [member.id]: reports }))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not generate a summary — try again')
    } finally {
      setGeneratingId('')
    }
  }

  function latestSummary(memberId) {
    const reports = reportsByMember[memberId] || []
    return reports.find((r) => r.report_type === 'member_summary')
  }

  const unclaimedCount = roster.filter((r) => !r.is_claimed).length

  return (
    <div>
      <Link to="/client/communities" style={{ fontSize: 12, color: 'var(--sub)' }}>&larr; Communities</Link>
      <h1 style={{ fontSize: 20, margin: '4px 0 20px' }}>Community members</h1>

      <div className="card" style={{ padding: 16, marginBottom: 20 }}>
        <div
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
          onClick={() => setShowRoster(!showRoster)}
        >
          <div style={{ fontWeight: 700 }}>
            Registration roster{' '}
            <span className="badge badge-pending" style={{ marginLeft: 6 }}>{unclaimedCount} unclaimed</span>
            <span className="badge badge-room" style={{ marginLeft: 4 }}>{roster.length} total</span>
          </div>
          <span style={{ fontSize: 12, color: 'var(--sub)' }}>{showRoster ? 'Hide' : 'Manage'}</span>
        </div>

        {showRoster && (
          <div style={{ marginTop: 14 }}>
            <p style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 10 }}>
              Members can only register with a number you've pre-issued here — an unrecognized or
              already-used number is rejected. Paste one or more numbers (space, comma, or newline separated).
            </p>
            {rosterError && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '8px 12px' }}>{rosterError}</div>}
            <form onSubmit={handleAddRoster} style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <input
                placeholder="e.g. 001, 002, 003"
                value={rosterInput}
                onChange={(e) => setRosterInput(e.target.value)}
                style={{ flex: 1, padding: 8, border: '1px solid var(--line)', borderRadius: 8 }}
              />
              <button type="submit" className="btn btn-primary" disabled={addingRoster}>{addingRoster ? 'Adding…' : 'Add'}</button>
            </form>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {roster.map((r) => (
                <span key={r.id} className={`badge ${r.is_claimed ? 'badge-room' : 'badge-agent'}`}>
                  {r.ilc_registration_number}{r.is_claimed ? ' · used' : ''}
                </span>
              ))}
              {roster.length === 0 && <span style={{ fontSize: 12, color: 'var(--sub)' }}>No roster numbers added yet.</span>}
            </div>
          </div>
        )}
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      {members.length === 0 ? (
        <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>
          No members yet — share this community's registration link to get started.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {members.map((m) => (
            <div key={m.id} className="card" style={{ padding: 16 }}>
              <div
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                onClick={() => toggleExpand(m)}
              >
                <div>
                  <div style={{ fontWeight: 700 }}>{m.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--sub)' }}>
                    {m.profile?.phone_number}{m.profile?.email ? ` · ${m.profile.email}` : ''}
                  </div>
                </div>
                <span className={`badge ${m.conversation_id ? 'badge-agent' : 'badge-pending'}`}>
                  {m.conversation_id ? 'chatting with agent' : 'not started yet'}
                </span>
              </div>

              {expandedId === m.id && (
                <div style={{ marginTop: 14, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
                  {m.profile?.extra_info && Object.keys(m.profile.extra_info).length > 0 && (
                    <div style={{ fontSize: 12, marginBottom: 10 }}>
                      {Object.entries(m.profile.extra_info).map(([k, v]) => (
                        <div key={k}><span style={{ color: 'var(--sub)' }}>{k}:</span> {String(v)}</div>
                      ))}
                    </div>
                  )}

                  <button
                    className="btn"
                    disabled={!m.conversation_id || generatingId === m.id}
                    title={!m.conversation_id ? "This member hasn't started chatting yet" : undefined}
                    onClick={() => handleGenerateSummary(m)}
                  >
                    {generatingId === m.id ? 'Generating…' : 'Generate / refresh summary'}
                  </button>

                  {latestSummary(m.id) ? (
                    <MemberSummary c={latestSummary(m.id).content} createdAt={latestSummary(m.id).created_at} />
                  ) : (
                    <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 10 }}>No summary generated yet.</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MemberSummary({ c, createdAt }) {
  return (
    <div style={{ marginTop: 12, fontSize: 13 }}>
      <div style={{ fontSize: 11, color: 'var(--sub)', marginBottom: 6 }}>
        Generated {new Date(createdAt).toLocaleString()}
      </div>
      <p style={{ marginTop: 0 }}>{c.profile_summary}</p>
      {(c.key_topics || []).length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {c.key_topics.map((t) => <span key={t} className="badge badge-room" style={{ marginRight: 4 }}>{t}</span>)}
        </div>
      )}
      {(c.needs_expressed || []).length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <span style={{ color: 'var(--sub)' }}>Needs expressed: </span>{c.needs_expressed.join(' · ')}
        </div>
      )}
      <div>
        <span className="badge badge-pending">{c.sentiment_overall}</span>{' '}
        <span style={{ color: 'var(--sub)' }}>{c.communication_notes}</span>
      </div>
    </div>
  )
}
