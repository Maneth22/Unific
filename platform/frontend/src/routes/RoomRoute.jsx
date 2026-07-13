import React from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/**
 * Hides a room's nav/routes from staff who don't hold a grant for it.
 * This is convenience only — the real boundary is
 * `require_room_access` on the server (app/core/security/dependencies.py),
 * enforced on every request regardless of what this component does.
 */
export default function RoomRoute({ room, minimum = 'read' }) {
  const { hasRoomAccess } = useAuth()

  if (!hasRoomAccess(room, minimum)) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
