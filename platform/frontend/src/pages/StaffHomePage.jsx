import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const ROOMS = [
  { key: 'accounts', label: 'Accounts Room', path: '/accounts' },
  { key: 'profiles', label: 'Profiles Room', path: '/profiles' },
  { key: 'meeting_room', label: 'Meeting Room', path: '/meeting-room' },
]

export default function StaffHomePage() {
  const { staff, hasRoomAccess } = useAuth()
  const accessible = ROOMS.filter((r) => hasRoomAccess(r.key))

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Welcome, {staff?.full_name}</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 24 }}>
        {staff?.is_superadmin
          ? 'Superadmin — full access to every room.'
          : `You have access to ${accessible.length} of 8 rooms.`}
      </p>

      {accessible.length === 0 && !staff?.is_superadmin ? (
        <div className="card" style={{ padding: 20 }}>
          No rooms granted yet. Ask a superadmin to grant access via Staff &amp; Access.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14 }}>
          {(staff?.is_superadmin ? ROOMS : accessible).map((room) => (
            <Link
              key={room.key}
              to={room.path}
              className="card"
              style={{ padding: 16, textDecoration: 'none', color: 'var(--ink)' }}
            >
              <div style={{ fontWeight: 700 }}>{room.label}</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
