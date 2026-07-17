import React, { useEffect, useState } from 'react'
import { approveRegistrationRequest, listRegistrationRequests, rejectRegistrationRequest } from '../api/profiles'

const STATUSES = ['pending', 'approved', 'rejected']

export default function StaffRegistrationRequestsPage() {
  const [status, setStatus] = useState('pending')
  const [requests, setRequests] = useState([])
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const [reasonById, setReasonById] = useState({})

  async function refresh() {
    setRequests(await listRegistrationRequests(status))
  }

  useEffect(() => { refresh() }, [status])

  async function handleApprove(id) {
    setError('')
    setBusyId(id)
    try {
      await approveRegistrationRequest(id)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not approve this request')
    } finally {
      setBusyId('')
    }
  }

  async function handleReject(id) {
    setError('')
    setBusyId(id)
    try {
      await rejectRegistrationRequest(id, reasonById[id] || '')
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not reject this request')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Client Registration Requests</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        Organisations that signed up for a dashboard account. Approving one creates their root
        community group and activates their login in one step.
      </p>

      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {STATUSES.map((s) => (
          <button
            key={s}
            className="btn"
            onClick={() => setStatus(s)}
            style={{ background: status === s ? 'var(--slate-bg)' : undefined }}
          >
            {s}
          </button>
        ))}
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      {requests.length === 0 ? (
        <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>No {status} requests.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {requests.map((r) => (
            <div key={r.id} className="card" style={{ padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 700 }}>{r.org_name}</div>
                  <div style={{ fontSize: 12, color: 'var(--sub)' }}>{r.contact_name} · {r.email}</div>
                  <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>
                    Submitted {new Date(r.created_at).toLocaleString()}
                  </div>
                  {r.status === 'rejected' && r.rejection_reason && (
                    <div style={{ fontSize: 12, marginTop: 6 }}>Reason: {r.rejection_reason}</div>
                  )}
                </div>
                <span className={`badge ${r.status === 'approved' ? 'badge-agent' : r.status === 'rejected' ? 'badge-alert' : 'badge-pending'}`}>
                  {r.status}
                </span>
              </div>

              {r.status === 'pending' && (
                <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
                  <button className="btn btn-primary" disabled={busyId === r.id} onClick={() => handleApprove(r.id)}>
                    {busyId === r.id ? 'Working…' : 'Approve'}
                  </button>
                  <input
                    placeholder="Rejection reason (optional)"
                    value={reasonById[r.id] || ''}
                    onChange={(e) => setReasonById({ ...reasonById, [r.id]: e.target.value })}
                    style={{ flex: 1, padding: 7, border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }}
                  />
                  <button className="btn" disabled={busyId === r.id} onClick={() => handleReject(r.id)}>
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
