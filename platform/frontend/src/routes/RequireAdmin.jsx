import React from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Sits inside ProtectedRoute (so "authenticated" is already guaranteed) —
// this only adds the admin-tier check. A regular (non-admin) staff
// account sees PermissionDeniedPage rather than a silent bounce; the real
// boundary is still server-side (`require_admin`), same spirit as every
// other route guard in this app — this is just a friendlier client-side
// signal of the same boundary.
export default function RequireAdmin() {
  const { isAdmin } = useAuth()
  if (!isAdmin) return <Navigate to="/403" replace />
  return <Outlet />
}
