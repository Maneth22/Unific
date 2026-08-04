import React from 'react'
import { Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import AppShell from './shared/AppShell'

const NAV_ITEMS = [
  { key: 'accounts', to: '/accounts', label: 'Accounts Room' },
  { key: 'profiles', to: '/profiles', label: 'Profiles Room' },
  { key: 'meeting_room', to: '/meeting-room', label: 'Meeting Room' },
  { key: 'requests', to: '/registration-requests', label: 'Client Requests', dividerBefore: true },
  { key: 'staff-mgmt', to: '/staff-management', label: 'Staff & Access' },
]

export default function StaffDashboardLayout() {
  const { staff, logout } = useAuth()

  return (
    <AppShell
      brand={
        <>
          UNIFIC <span style={{ color: 'var(--token)' }}>Platform</span>
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
