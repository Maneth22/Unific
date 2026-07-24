import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { clientLogin, clientLogout, clientRefresh } from '../api/clientAuth'
import { clientStaffLogin, clientStaffLogout, clientStaffRefresh } from '../api/clientStaffAuth'
import { setAccessToken, setRefreshEndpoint, setUnauthorizedHandler } from '../api/client'

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

  const clearAuth = useCallback(() => {
    setAccessToken(null)
    setClientUser(null)
    setActorType(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(clearAuth)

    async function silentRefresh() {
      try {
        const data = await clientRefresh()
        setRefreshEndpoint('/profiles/client/refresh')
        setAccessToken(data.access_token)
        setClientUser(data.client)
        setActorType('owner')
        return
      } catch {
        // Not an owner session (or none) — try the client-staff cookie.
      }
      try {
        const data = await clientStaffRefresh()
        setRefreshEndpoint('/profiles/client-staff/refresh')
        setAccessToken(data.access_token)
        setClientUser(data.client_staff)
        setActorType('staff')
      } catch {
        setAccessToken(null)
        setClientUser(null)
        setActorType(null)
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

  const value = useMemo(
    () => ({
      clientUser,
      actorType,
      isOwner: actorType === 'owner',
      loading,
      isAuthenticated: !!clientUser,
      login,
      logout,
    }),
    [clientUser, actorType, loading, login, logout]
  )

  return <ClientAuthContext.Provider value={value}>{children}</ClientAuthContext.Provider>
}

export function useClientAuth() {
  const ctx = useContext(ClientAuthContext)
  if (!ctx) throw new Error('useClientAuth must be used within ClientAuthProvider')
  return ctx
}
