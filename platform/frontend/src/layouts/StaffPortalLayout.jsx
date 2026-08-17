import React from 'react'
import { Outlet } from 'react-router-dom'
import { CheckSquare, Inbox, Video } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import AppShell from './shared/AppShell'
import Button from '../components/ui/Button.jsx'
import logo from '../assets/logo.png'

// The "common interface" a regular (non-admin) staff account gets —
// deliberately minimal: their own tasks/progress and an inbox, nothing
// else (no client data, no cost/API dashboards). Mirrors
// StaffDashboardLayout's visual shell but with its own, much shorter nav.
const NAV_ITEMS = [
  { key: 'tasks', to: '/portal', label: 'My Tasks', end: true, icon: CheckSquare },
  { key: 'inbox', to: '/portal/inbox', label: 'Inbox', icon: Inbox },
  { key: 'meetings', to: '/portal/meetings', label: 'Meetings', icon: Video },
]

export default function StaffPortalLayout() {
  const { staff, logout } = useAuth()

  return (
    <AppShell
      brand={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <img src={logo} alt="" width={24} height={24} style={{ display: 'block' }} />
          UNIFIC <span style={{ color: 'var(--token)' }}>Staff</span>
        </span>
      }
      navItems={NAV_ITEMS}
      topbarUser={staff ? { name: staff.full_name, subtitle: 'Staff member' } : undefined}
      onLogout={logout}
      footer={
        <>
          <div style={{ fontWeight: 700, color: '#fff' }}>{staff?.full_name}</div>
          <div style={{ marginBottom: 8 }}>{staff?.email}</div>
          <Button variant="secondary" style={{ width: '100%' }} onClick={logout}>
            Log out
          </Button>
        </>
      }
    >
      <Outlet />
    </AppShell>
  )
}
