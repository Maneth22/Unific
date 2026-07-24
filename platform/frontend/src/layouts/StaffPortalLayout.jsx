import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// The "common interface" a regular (non-admin) staff account gets —
// deliberately minimal: their own tasks/progress and an inbox, nothing
// else (no client data, no cost/API dashboards). Mirrors
// StaffDashboardLayout's visual shell but with its own, much shorter nav.
export default function StaffPortalLayout() {
  const { staff, logout } = useAuth()

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <aside
        style={{
          width: 220,
          borderRight: '1px solid var(--line)',
          background: 'var(--surface)',
          padding: '18px 12px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ fontWeight: 800, fontSize: 15, padding: '0 8px 18px' }}>
          UNIFIC <span style={{ color: 'var(--token)' }}>Staff</span>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
          {[
            { to: '/portal', label: 'My Tasks', end: true },
            { to: '/portal/inbox', label: 'Inbox' },
          ].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              style={({ isActive }) => ({
                padding: '9px 10px',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: 'none',
                color: isActive ? 'white' : 'var(--ink)',
                background: isActive ? 'var(--slate)' : 'transparent',
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div style={{ borderTop: '1px solid var(--line)', paddingTop: 12, fontSize: 12 }}>
          <div style={{ fontWeight: 700 }}>{staff?.full_name}</div>
          <div style={{ color: 'var(--sub)', marginBottom: 8 }}>{staff?.email}</div>
          <button className="btn" style={{ width: '100%' }} onClick={logout}>
            Log out
          </button>
        </div>
      </aside>

      <main style={{ flex: 1, padding: 28, overflowY: 'auto' }}>
        <Outlet />
      </main>
    </div>
  )
}
