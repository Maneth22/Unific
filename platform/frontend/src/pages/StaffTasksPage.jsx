import React, { useEffect, useState } from 'react'
import { addTaskUpdate, getTask, listMyTasks } from '../api/tasking'

const STATUS_BADGE = {
  open: 'badge-pending',
  in_progress: 'badge-agent',
  blocked: 'badge-alert',
  completed: 'badge-room',
  cancelled: 'badge-alert',
}

const STATUS_OPTIONS = ['open', 'in_progress', 'blocked', 'completed', 'cancelled']

export default function StaffTasksPage() {
  const [tasks, setTasks] = useState([])
  const [expandedId, setExpandedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [note, setNote] = useState('')
  const [progressStatus, setProgressStatus] = useState('')
  const [isConcern, setIsConcern] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function refresh() {
    setTasks(await listMyTasks())
  }

  useEffect(() => { refresh() }, [])

  async function toggleExpand(task) {
    if (expandedId === task.id) {
      setExpandedId('')
      setDetail(null)
      return
    }
    setExpandedId(task.id)
    setDetail(await getTask(task.id))
    setNote('')
    setProgressStatus('')
    setIsConcern(false)
  }

  async function handleAddUpdate(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await addTaskUpdate(expandedId, {
        note,
        progress_status: progressStatus || null,
        is_concern: isConcern,
      })
      setDetail(await getTask(expandedId))
      await refresh()
      setNote('')
      setProgressStatus('')
      setIsConcern(false)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add update')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>My Tasks</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        Tasks assigned to you. Add a progress update or flag a concern for the admin — both show up on their dashboard.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {tasks.map((task) => (
          <div key={task.id} className="card" style={{ padding: 14 }}>
            <div
              className="card-clickable"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderRadius: 6, padding: '2px 4px', margin: '-2px -4px' }}
              onClick={() => toggleExpand(task)}
            >
              <div>
                <span className={`badge ${STATUS_BADGE[task.status] || 'badge-room'}`}>{task.status}</span>{' '}
                <strong>{task.title}</strong>
                {task.description && <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 2 }}>{task.description}</div>}
              </div>
              {task.due_date && <div style={{ fontSize: 12, color: 'var(--sub)' }}>Due {task.due_date}</div>}
            </div>

            {expandedId === task.id && detail && (
              <div style={{ marginTop: 12, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>History</div>
                {detail.updates.length === 0 && <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 10 }}>No updates yet.</div>}
                {detail.updates.map((u) => (
                  <div key={u.id} style={{ fontSize: 12, marginBottom: 8, paddingBottom: 8, borderBottom: '1px solid var(--line)' }}>
                    <div style={{ display: 'flex', gap: 6, marginBottom: 2 }}>
                      {u.progress_status && <span className={`badge ${STATUS_BADGE[u.progress_status] || 'badge-room'}`}>{u.progress_status}</span>}
                      {u.is_concern && <span className="badge badge-alert">concern</span>}
                      <span style={{ color: 'var(--sub)' }}>{new Date(u.created_at).toLocaleString()}</span>
                    </div>
                    <div>{u.note}</div>
                  </div>
                ))}

                {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '8px 12px' }}>{error}</div>}

                <form onSubmit={handleAddUpdate} style={{ display: 'grid', gap: 8 }}>
                  <textarea
                    required
                    placeholder="What's the update?"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8, minHeight: 60, fontFamily: 'inherit' }}
                  />
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    <select value={progressStatus} onChange={(e) => setProgressStatus(e.target.value)} style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8 }}>
                      <option value="">— no status change —</option>
                      {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                      <input type="checkbox" checked={isConcern} onChange={(e) => setIsConcern(e.target.checked)} />
                      Flag as a concern
                    </label>
                    <button type="submit" className="btn btn-primary" disabled={submitting} style={{ marginLeft: 'auto' }}>
                      {submitting ? 'Posting…' : 'Post update'}
                    </button>
                  </div>
                </form>
              </div>
            )}
          </div>
        ))}
        {tasks.length === 0 && <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>No tasks assigned yet.</div>}
      </div>
    </div>
  )
}
