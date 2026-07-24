import React from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Sits inside ProtectedRoute (so "authenticated" is already guaranteed) —
// this only adds the admin-tier check. A regular (non-admin) staff
// account gets redirected to their own portal rather than an error page;
// the real boundary is server-side (`require_admin`), same spirit as
// every other route guard in this app.
export default function RequireAdmin() {
  const { isAdmin } = useAuth()
  if (!isAdmin) return <Navigate to="/portal" replace />
  return <Outlet />
}
