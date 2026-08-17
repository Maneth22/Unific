import React from 'react'
import { Outlet } from 'react-router-dom'
import { Bell, Users, Video, Wallet, Wrench } from 'lucide-react'
import { useClientAuth } from '../context/ClientAuthContext'
import AppShell from './shared/AppShell'
import Button from '../components/ui/Button.jsx'
import logo from '../assets/logo.png'

export default function ClientDashboardLayout() {
  const { clientUser, isOwner, logout } = useClientAuth()

  const navItems = [
    ...(isOwner ? [{ key: 'accounts', to: '/client', label: 'Accounts', end: true, icon: Wallet }] : []),
    { key: 'profiles', to: '/client/communities', label: 'Profiles', icon: Users },
    { key: 'meeting_room', to: '/client/meeting-room', label: 'Meeting Room', icon: Video },
    { key: 'services', to: '/client/services', label: 'Services', icon: Wrench },
    { key: 'inbox', to: '/client/inbox', label: 'Notices / Inbox', icon: Bell },
  ]

  return (
    <AppShell
      brand={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <img src={logo} alt="" width={24} height={24} style={{ display: 'block' }} />
          UNIFIC
        </span>
      }
      navItems={navItems}
      topbarUser={clientUser ? { name: clientUser.full_name, subtitle: isOwner ? 'Organisation owner' : 'Client' } : undefined}
      onLogout={logout}
      footer={
        <>
          <div style={{ fontWeight: 700, color: '#fff' }}>{clientUser?.full_name}</div>
          <div style={{ marginBottom: 8 }}>{clientUser?.email}</div>
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
