import React from 'react'
import { Outlet } from 'react-router-dom'
import { useClientAuth } from '../context/ClientAuthContext'
import AppShell from './shared/AppShell'

export default function ClientDashboardLayout() {
  const { clientUser, isOwner, logout } = useClientAuth()

  const navItems = [
    ...(isOwner ? [{ key: 'accounts', to: '/client', label: 'Accounts', end: true }] : []),
    { key: 'profiles', to: '/client/communities', label: 'Profiles' },
    { key: 'meeting_room', to: '/client/meeting-room', label: 'Meeting Room' },
    { key: 'services', to: '/client/services', label: 'Services' },
    { key: 'inbox', to: '/client/inbox', label: 'Notices / Inbox' },
  ]

  return (
    <AppShell
      brand="UNIFIC"
      navItems={navItems}
      footer={
        <>
          <div style={{ fontWeight: 700 }}>{clientUser?.full_name}</div>
          <div style={{ color: 'var(--sub)', marginBottom: 8 }}>{clientUser?.email}</div>
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
