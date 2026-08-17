import React from 'react'
import { Outlet } from 'react-router-dom'
import { LayoutDashboard, MessageSquare, ShieldCheck, Users, Video, Wallet, Inbox } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import AppShell from './shared/AppShell'
import Button from '../components/ui/Button.jsx'
import logo from '../assets/logo.png'

// 'dashboard' is the fix for a previously-orphaned route: /staff (rendering
// StaffHomePage) existed and was reachable, but had no sidebar entry
// anywhere — added here as the first item.
const NAV_ITEMS = [
  { key: 'dashboard', to: '/staff', label: 'Dashboard', end: true, icon: LayoutDashboard },
  { key: 'accounts', to: '/accounts', label: 'Accounts Room', icon: Wallet },
  { key: 'profiles', to: '/profiles', label: 'Profiles Room', icon: Users },
  { key: 'meeting_room', to: '/meeting-room', label: 'Meeting Room', icon: Video },
  { key: 'whatsapp_messages', to: '/whatsapp-messages', label: 'WhatsApp Messages', icon: MessageSquare },
  { key: 'requests', to: '/registration-requests', label: 'Client Requests', dividerBefore: true, icon: Inbox },
  { key: 'staff-mgmt', to: '/staff-management', label: 'Staff & Access', icon: ShieldCheck },
]

export default function StaffDashboardLayout() {
  const { staff, logout } = useAuth()

  return (
    <AppShell
      brand={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <img src={logo} alt="" width={24} height={24} style={{ display: 'block' }} />
          UNIFIC <span style={{ color: 'var(--token)' }}>Platform</span>
        </span>
      }
      navItems={NAV_ITEMS}
      topbarUser={staff ? { name: staff.full_name, subtitle: 'Administrator' } : undefined}
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
