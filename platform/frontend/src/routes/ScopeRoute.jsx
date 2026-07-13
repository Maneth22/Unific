import React from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useClientAuth } from '../context/ClientAuthContext'

/**
 * Gates the client dashboard behind a client login. The real scope
 * boundary (which identities a client can reach) is enforced server-side
 * on every request by `require_identity_scope` — this route guard only
 * covers "is anyone logged in at all", mirroring ProtectedRoute's role
 * for the staff dashboard.
 */
export default function ScopeRoute() {
  const { isAuthenticated, loading } = useClientAuth()
  const location = useLocation()

  if (loading) return null
  if (!isAuthenticated) {
    return <Navigate to="/client/login" state={{ from: location }} replace />
  }
  return <Outlet />
}
