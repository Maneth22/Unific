import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { clientLogin, clientLogout, clientRefresh } from '../api/clientAuth'
import { clientStaffLogin, clientStaffLogout, clientStaffRefresh } from '../api/clientStaffAuth'
import { setAccessToken, setRefreshEndpoint, setUnauthorizedHandler } from '../api/client'
import useIdleLogout, { IDLE_TIMEOUT_MS } from '../hooks/useIdleLogout'

const ClientAuthContext = createContext(null)

/**
 * One context for both client-side login types — the org owner/co-owner
 * (`ClientUser`, full access) and limited client-staff (`ClientStaffUser`,
 * everything except money/account-management routes) — since they share
 * the same dashboard shell and most of the same pages, just with the
 * Accounts (money) view gated off for staff. `actorType` ('owner' | 'staff')
 * and `isOwner` tell the rest of the app which one is signed in; `clientUser`
 * is normalized to the same shape either way (id/email/full_name/identity_id).
 */
export function ClientAuthProvider({ children }) {
  const [clientUser, setClientUser] = useState(null)
  const [actorType, setActorType] = useState(null) // 'owner' | 'staff'
  const [loading, setLoading] = useState(true)
  // Only set when BOTH the owner and client-staff silent-refresh attempts
  // below ultimately fail to authenticate AND at least one of those
  // failures was a genuine network error (no response) rather than a
  // normal 401 — a plain "no valid session" case (the expected outcome for
  // a first-time visitor) must never trip this. See App.jsx's
  // ClientAreaGate.
  const [connectionError, setConnectionError] = useState(false)

  const clearAuth = useCallback(() => {
    setAccessToken(null)
    setClientUser(null)
    setActorType(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(clearAuth)

    async function silentRefresh() {
      let sawNetworkError = false
      try {
        const data = await clientRefresh()
        setRefreshEndpoint('/profiles/client/refresh')
        setAccessToken(data.access_token)
        setClientUser(data.client)
        setActorType('owner')
        return
      } catch (err) {
        // Not an owner session (or none) — try the client-staff cookie.
        if (!err.response) sawNetworkError = true
      }
      try {
        const data = await clientStaffRefresh()
        setRefreshEndpoint('/profiles/client-staff/refresh')
        setAccessToken(data.access_token)
        setClientUser(data.client_staff)
        setActorType('staff')
      } catch (err) {
        if (!err.response) sawNetworkError = true
        setAccessToken(null)
        setClientUser(null)
        setActorType(null)
        if (sawNetworkError) setConnectionError(true)
      }
    }

    silentRefresh().finally(() => setLoading(false))
  }, [clearAuth])

  const login = useCallback(async (email, password, loginActorType = 'owner') => {
    if (loginActorType === 'staff') {
      const data = await clientStaffLogin(email, password)
      setRefreshEndpoint('/profiles/client-staff/refresh')
      setAccessToken(data.access_token)
      setClientUser(data.client_staff)
      setActorType('staff')
      return data
    }
    const data = await clientLogin(email, password)
    setRefreshEndpoint('/profiles/client/refresh')
    setAccessToken(data.access_token)
    setClientUser(data.client)
    setActorType('owner')
    return data
  }, [])

  const logout = useCallback(async () => {
    try {
      if (actorType === 'staff') {
        await clientStaffLogout()
      } else {
        await clientLogout()
      }
    } finally {
      clearAuth()
    }
  }, [actorType, clearAuth])

  // Security: auto sign-out after IDLE_TIMEOUT_MS of no mouse/keyboard/
  // touch/scroll activity, redirecting to the client login with a reason
  // flag so it can show a "signed out due to inactivity" banner.
  const navigate = useNavigate()
  const handleIdle = useCallback(() => {
    logout()
    navigate('/login?reason=idle', { replace: true })
  }, [logout, navigate])
  useIdleLogout(!!clientUser, IDLE_TIMEOUT_MS, handleIdle)

  const value = useMemo(
    () => ({
      clientUser,
      actorType,
      isOwner: actorType === 'owner',
      loading,
      connectionError,
      isAuthenticated: !!clientUser,
      login,
      logout,
    }),
    [clientUser, actorType, loading, connectionError, login, logout]
  )

  return <ClientAuthContext.Provider value={value}>{children}</ClientAuthContext.Provider>
}

export function useClientAuth() {
  const ctx = useContext(ClientAuthContext)
  if (!ctx) throw new Error('useClientAuth must be used within ClientAuthProvider')
  return ctx
}
