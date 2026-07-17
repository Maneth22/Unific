import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const ROOMS = [
  { key: 'accounts', label: 'Accounts Room', path: '/accounts' },
  { key: 'profiles', label: 'Profiles Room', path: '/profiles' },
  { key: 'meeting_room', label: 'Meeting Room', path: '/meeting-room' },
]

export default function StaffHomePage() {
  const { staff } = useAuth()

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Welcome, {staff?.full_name}</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 24 }}>Admin — full access to every room.</p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14 }}>
        {ROOMS.map((room) => (
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
    </div>
  )
}
