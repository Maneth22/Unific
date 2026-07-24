import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useClientAuth } from '../context/ClientAuthContext'

export default function ClientDashboardLayout() {
  const { clientUser, isOwner, logout } = useClientAuth()

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <aside
        style={{
          width: 200,
          borderRight: '1px solid var(--line)',
          background: 'var(--surface)',
          padding: '18px 12px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ fontWeight: 800, fontSize: 15, padding: '0 8px 18px' }}>
          UNIFIC
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
          {isOwner && <NavItem to="/client" end label="Accounts" />}
          <NavItem to="/client/communities" label="Profiles" />
          <NavItem to="/client/meeting-room" label="Meeting Room" />
          <NavItem to="/client/services" label="Services" />
          <NavItem to="/client/inbox" label="Notices / Inbox" />
        </nav>

        <div style={{ borderTop: '1px solid var(--line)', paddingTop: 12, fontSize: 12 }}>
          <div style={{ fontWeight: 700 }}>{clientUser?.full_name}</div>
          <div style={{ color: 'var(--sub)', marginBottom: 8 }}>{clientUser?.email}</div>
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

function NavItem({ to, label, end }) {
  return (
    <NavLink
      to={to}
      end={end}
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
      {label}
    </NavLink>
  )
}
