import React, { useEffect, useState } from 'react'
import { Inbox } from 'lucide-react'
import { approveRegistrationRequest, listRegistrationRequests, rejectRegistrationRequest } from '../api/profiles'
import Card from '../components/ui/Card.jsx'
import Badge from '../components/ui/Badge.jsx'
import Button from '../components/ui/Button.jsx'
import Input from '../components/ui/Input.jsx'
import { SkeletonBlock } from '../components/ui/Skeleton.jsx'

const STATUSES = ['pending', 'approved', 'rejected']

export default function StaffRegistrationRequestsPage() {
  const [status, setStatus] = useState('pending')
  const [requests, setRequests] = useState(null)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const [reasonById, setReasonById] = useState({})

  async function refresh() {
    setRequests(await listRegistrationRequests(status))
  }

  useEffect(() => { setRequests(null); refresh() }, [status])

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

      <div className="ui-segmented" style={{ marginBottom: 16 }}>
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={`ui-segmented-btn${status === s ? ' ui-segmented-btn--active' : ''}`}
            style={{ textTransform: 'capitalize' }}
          >
            {s}
          </button>
        ))}
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      {requests === null ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBlock key={i} height={78} />
          ))}
        </div>
      ) : requests.length === 0 ? (
        <Card>
          <div className="empty-state">
            <span className="empty-state-icon">
              <Inbox size={20} />
            </span>
            <h3>No {status} requests</h3>
            <p>New registration requests in this status will show up here.</p>
          </div>
        </Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {requests.map((r) => (
            <Card key={r.id} padding={16}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700 }}>{r.org_name}</div>
                  <div style={{ fontSize: 12, color: 'var(--sub)' }}>{r.contact_name} · {r.email}</div>
                  <div style={{ fontSize: 11, color: 'var(--sub)', marginTop: 4 }}>
                    Submitted {new Date(r.created_at).toLocaleString()}
                  </div>
                  {r.status === 'rejected' && r.rejection_reason && (
                    <div style={{ fontSize: 12, marginTop: 6 }}>Reason: {r.rejection_reason}</div>
                  )}
                </div>
                <Badge status={r.status} />
              </div>

              {r.status === 'pending' && (
                <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'flex-end' }}>
                  <Button variant="primary" loading={busyId === r.id} onClick={() => handleApprove(r.id)}>
                    Approve
                  </Button>
                  <div style={{ flex: 1 }}>
                    <Input
                      placeholder="Rejection reason (optional)"
                      value={reasonById[r.id] || ''}
                      onChange={(e) => setReasonById({ ...reasonById, [r.id]: e.target.value })}
                    />
                  </div>
                  <Button variant="secondary" disabled={busyId === r.id} onClick={() => handleReject(r.id)}>
                    Reject
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
