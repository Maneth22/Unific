import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { staffLogin, staffLogout, staffRefresh, staffBootstrap } from '../api/auth'
import { setAccessToken, setRefreshEndpoint, setUnauthorizedHandler } from '../api/client'
import useIdleLogout, { IDLE_TIMEOUT_MS } from '../hooks/useIdleLogout'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [staff, setStaff] = useState(null)
  const [loading, setLoading] = useState(true)
  // Only set when the initial silent-refresh below fails with a genuine
  // network error (no response at all — backend unreachable), never for a
  // normal 401 ("no valid session yet", the expected case for a first-time
  // visitor). See App.jsx's StaffAreaGate, which renders ConnectionLostPage
  // instead of the dashboard/login flow when this is true.
  const [connectionError, setConnectionError] = useState(false)

  const clearAuth = useCallback(() => {
    setAccessToken(null)
    setStaff(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(clearAuth)
    setRefreshEndpoint('/auth/staff/refresh')
    // Silent refresh on load: the access token lives only in memory, so
    // a page reload has none — the httpOnly refresh cookie (if any valid
    // session exists) is what re-establishes the session here.
    staffRefresh()
      .then((data) => {
        setAccessToken(data.access_token)
        setStaff(data.staff)
      })
      .catch((err) => {
        setAccessToken(null)
        setStaff(null)
        if (!err.response) setConnectionError(true)
      })
      .finally(() => setLoading(false))
  }, [clearAuth])

  const login = useCallback(async (email, password) => {
    const data = await staffLogin(email, password)
    setAccessToken(data.access_token)
    setStaff(data.staff)
    return data
  }, [])

  const bootstrap = useCallback(async (email, password, fullName) => {
    const data = await staffBootstrap(email, password, fullName)
    setAccessToken(data.access_token)
    setStaff(data.staff)
    return data
  }, [])

  const logout = useCallback(async () => {
    try {
      await staffLogout()
    } finally {
      clearAuth()
    }
  }, [clearAuth])

  const refreshStaff = useCallback(async () => {
    const data = await staffRefresh()
    setAccessToken(data.access_token)
    setStaff(data.staff)
    return data
  }, [])

  // Security: auto sign-out after IDLE_TIMEOUT_MS of no mouse/keyboard/
  // touch/scroll activity, redirecting to the staff login with a reason
  // flag so it can show a "signed out due to inactivity" banner.
  const navigate = useNavigate()
  const handleIdle = useCallback(() => {
    logout()
    navigate('/support/login?reason=idle', { replace: true })
  }, [logout, navigate])
  useIdleLogout(!!staff, IDLE_TIMEOUT_MS, handleIdle)

  const value = useMemo(
    () => ({
      staff,
      loading,
      connectionError,
      isAuthenticated: !!staff,
      isAdmin: staff?.tier === 'admin',
      login,
      bootstrap,
      logout,
      refreshStaff,
    }),
    [staff, loading, connectionError, login, bootstrap, logout, refreshStaff]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
