import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listCategories, listStaff } from '../../api/staffDirectory'

// Deliberately separate from the client identity tree (IdentityTree.jsx) —
// staff are never identity-tree nodes, and mixing the two views is exactly
// what the admin asked not to do. Read-only here; full management
// (create/edit tier/category) lives on the "Staff & Access" page.
export default function StaffDirectoryPanel() {
  const [staffList, setStaffList] = useState([])
  const [categories, setCategories] = useState([])

  useEffect(() => {
    Promise.all([listStaff(), listCategories()]).then(([s, c]) => {
      setStaffList(s)
      setCategories(c)
    })
  }, [])

  const categoryName = (id) => categories.find((c) => c.id === id)?.name

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 14 }}>
        Every UNIFIC staff account — kept separate from clients above. Manage tier/category on{' '}
        <Link to="/staff-management">Staff &amp; Access</Link>.
      </p>
      <div className="card" style={{ padding: 0 }}>
        {staffList.map((s) => (
          <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: '1px solid var(--line)', fontSize: 13 }}>
            <div style={{ flex: 1 }}>
              <strong>{s.full_name}</strong>
              <div style={{ fontSize: 12, color: 'var(--sub)' }}>{s.email}</div>
            </div>
            {s.category_id && <span className="badge badge-room">{categoryName(s.category_id)}</span>}
            <span className={`badge ${s.tier === 'admin' ? 'badge-account' : 'badge-pending'}`}>{s.tier}</span>
            {!s.is_active && <span className="badge badge-alert">inactive</span>}
          </div>
        ))}
        {staffList.length === 0 && <div style={{ padding: 20, color: 'var(--sub)' }}>No staff yet.</div>}
      </div>
    </div>
  )
}
