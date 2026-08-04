import React from 'react'
import { Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import AppShell from './shared/AppShell'

// The "common interface" a regular (non-admin) staff account gets —
// deliberately minimal: their own tasks/progress and an inbox, nothing
// else (no client data, no cost/API dashboards). Mirrors
// StaffDashboardLayout's visual shell but with its own, much shorter nav.
const NAV_ITEMS = [
  { key: 'tasks', to: '/portal', label: 'My Tasks', end: true },
  { key: 'inbox', to: '/portal/inbox', label: 'Inbox' },
  { key: 'meetings', to: '/portal/meetings', label: 'Meetings' },
]

export default function StaffPortalLayout() {
  const { staff, logout } = useAuth()

  return (
    <AppShell
      brand={
        <>
          UNIFIC <span style={{ color: 'var(--token)' }}>Staff</span>
        </>
      }
      navItems={NAV_ITEMS}
      footer={
        <>
          <div style={{ fontWeight: 700 }}>{staff?.full_name}</div>
          <div style={{ color: 'var(--sub)', marginBottom: 8 }}>{staff?.email}</div>
          <button className="btn" style={{ width: '100%' }} onClick={logout}>
            Log out
          </button>
        </>
      }
    >
      <Outlet />
    </AppShell>
  )
}
