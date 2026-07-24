import React, { useEffect, useState } from 'react'
import { createStaff } from '../api/auth'
import { createCategory, listCategories, listStaff, updateStaff } from '../api/staffDirectory'
import { createTask } from '../api/tasking'

export default function StaffManagementPage() {
  const [staffList, setStaffList] = useState([])
  const [categories, setCategories] = useState([])
  const [form, setForm] = useState({ email: '', password: '', full_name: '', tier: 'staff', category_id: '' })
  const [categoryForm, setCategoryForm] = useState({ name: '', description: '' })
  const [taskForm, setTaskForm] = useState({ title: '', description: '', assigned_to_staff_id: '', due_date: '' })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    const [s, c] = await Promise.all([listStaff(), listCategories()])
    setStaffList(s)
    setCategories(c)
  }

  useEffect(() => { refresh() }, [])

  const categoryName = (id) => categories.find((c) => c.id === id)?.name || ''

  async function handleCreateCategory(e) {
    e.preventDefault()
    setError('')
    try {
      await createCategory(categoryForm)
      setCategoryForm({ name: '', description: '' })
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create category')
    }
  }

  async function handleCreateStaff(e) {
    e.preventDefault()
    setError('')
    try {
      const staff = await createStaff(form.email, form.password, form.full_name, form.tier, form.category_id || null)
      setForm({ email: '', password: '', full_name: '', tier: 'staff', category_id: '' })
      setMessage(`Created ${staff.email} (${staff.tier}).`)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create staff account')
    }
  }

  async function handleTierChange(staffId, tier) {
    setError('')
    try {
      await updateStaff(staffId, { tier })
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update staff')
    }
  }

  async function handleCategoryChange(staffId, category_id) {
    setError('')
    try {
      await updateStaff(staffId, { category_id: category_id || null })
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update staff')
    }
  }

  async function handleActiveToggle(staffId, is_active) {
    setError('')
    try {
      await updateStaff(staffId, { is_active })
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update staff')
    }
  }

  async function handleAssignTask(e) {
    e.preventDefault()
    setError('')
    try {
      await createTask({ ...taskForm, due_date: taskForm.due_date || null })
      setTaskForm({ title: '', description: '', assigned_to_staff_id: '', due_date: '' })
      setMessage('Task assigned.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not assign task')
    }
  }

  return (
    <div style={{ maxWidth: 900 }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Staff &amp; Access</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        Admin accounts see and manage everything. Regular staff accounts only see their own
        assigned tasks and inbox — never client data or cost/API dashboards.
      </p>

      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{message}</div>}
      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <form onSubmit={handleCreateCategory} className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Create a category</div>
          <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 10 }}>
            An organizational label for staff (e.g. "Developer", "Marketing") — no access implications.
          </div>
          <input
            placeholder="Category name" required value={categoryForm.name}
            onChange={(e) => setCategoryForm({ ...categoryForm, name: e.target.value })}
            style={inputStyle}
          />
          <input
            placeholder="Description (optional)" value={categoryForm.description}
            onChange={(e) => setCategoryForm({ ...categoryForm, description: e.target.value })}
            style={inputStyle}
          />
          <button type="submit" className="btn btn-primary">Create category</button>
        </form>

        <form onSubmit={handleCreateStaff} className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Create staff account</div>
          <input placeholder="Full name" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} style={inputStyle} />
          <input type="email" placeholder="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} style={inputStyle} />
          <input type="password" placeholder="Temporary password (12+ chars)" required minLength={12} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} style={inputStyle} />
          <div style={{ display: 'flex', gap: 8 }}>
            <select value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })} style={{ ...inputStyle, flex: 1 }}>
              <option value="staff">Staff</option>
              <option value="admin">Admin</option>
            </select>
            <select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })} style={{ ...inputStyle, flex: 1 }}>
              <option value="">— no category —</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <button type="submit" className="btn btn-primary">Create</button>
        </form>
      </div>

      <form onSubmit={handleAssignTask} className="card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Assign a task</div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
          <input placeholder="Title" required value={taskForm.title} onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} style={inputStyle} />
          <select required value={taskForm.assigned_to_staff_id} onChange={(e) => setTaskForm({ ...taskForm, assigned_to_staff_id: e.target.value })} style={inputStyle}>
            <option value="">— assign to —</option>
            {staffList.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
          </select>
          <input type="date" value={taskForm.due_date} onChange={(e) => setTaskForm({ ...taskForm, due_date: e.target.value })} style={inputStyle} />
        </div>
        <textarea
          placeholder="Description (optional)" value={taskForm.description}
          onChange={(e) => setTaskForm({ ...taskForm, description: e.target.value })}
          style={{ ...inputStyle, minHeight: 60, fontFamily: 'inherit', width: '100%' }}
        />
        <button type="submit" className="btn btn-primary">Assign task</button>
      </form>

      <div className="card" style={{ padding: 16 }}>
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Staff directory</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {staffList.map((s) => (
            <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}>
              <div style={{ flex: 1 }}>
                <strong>{s.full_name}</strong>
                <div style={{ fontSize: 12, color: 'var(--sub)' }}>{s.email}</div>
              </div>
              <span className={`badge ${s.tier === 'admin' ? 'badge-account' : 'badge-room'}`}>{s.tier}</span>
              <select value={s.tier} onChange={(e) => handleTierChange(s.id, e.target.value)} style={{ ...inputStyle, width: 100 }}>
                <option value="staff">staff</option>
                <option value="admin">admin</option>
              </select>
              <select value={s.category_id || ''} onChange={(e) => handleCategoryChange(s.id, e.target.value)} style={{ ...inputStyle, width: 140 }}>
                <option value="">— no category —</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={s.is_active} onChange={(e) => handleActiveToggle(s.id, e.target.checked)} />
                active
              </label>
            </div>
          ))}
          {staffList.length === 0 && <div style={{ color: 'var(--sub)' }}>No staff yet.</div>}
        </div>
      </div>
    </div>
  )
}

const inputStyle = { width: '100%', padding: 8, marginBottom: 8, border: '1px solid var(--line)', borderRadius: 8 }
