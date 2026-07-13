import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const ROOMS = [
  { key: 'accounts', label: 'Accounts Room', path: '/accounts' },
  { key: 'profiles', label: 'Profiles Room', path: '/profiles' },
  { key: 'meeting_room', label: 'Meeting Room', path: '/meeting-room' },
]

export default function StaffDashboardLayout() {
  const { staff, hasRoomAccess, logout } = useAuth()

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
          UNIFIC <span style={{ color: 'var(--token)' }}>Platform</span>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
          {ROOMS.map((room) =>
            hasRoomAccess(room.key) ? (
              <NavLink
                key={room.key}
                to={room.path}
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
                {room.label}
              </NavLink>
            ) : null
          )}

          {staff?.is_superadmin && (
            <NavLink
              to="/staff-management"
              style={({ isActive }) => ({
                padding: '9px 10px',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: 'none',
                color: isActive ? 'white' : 'var(--ink)',
                background: isActive ? 'var(--slate)' : 'transparent',
                marginTop: 10,
              })}
            >
              Staff &amp; Access
            </NavLink>
          )}
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
