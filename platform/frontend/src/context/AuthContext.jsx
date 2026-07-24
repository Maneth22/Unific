import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { staffLogin, staffLogout, staffRefresh, staffBootstrap } from '../api/auth'
import { setAccessToken, setRefreshEndpoint, setUnauthorizedHandler } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [staff, setStaff] = useState(null)
  const [loading, setLoading] = useState(true)

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
      .catch(() => {
        setAccessToken(null)
        setStaff(null)
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

  const value = useMemo(
    () => ({
      staff,
      loading,
      isAuthenticated: !!staff,
      isAdmin: staff?.tier === 'admin',
      login,
      bootstrap,
      logout,
      refreshStaff,
    }),
    [staff, loading, login, bootstrap, logout, refreshStaff]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
