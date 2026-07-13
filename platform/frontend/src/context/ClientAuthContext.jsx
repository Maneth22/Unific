import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { clientLogin, clientLogout, clientRefresh } from '../api/clientAuth'
import { setAccessToken, setRefreshEndpoint, setUnauthorizedHandler } from '../api/client'

const ClientAuthContext = createContext(null)

/**
 * Mirrors AuthContext (staff) but talks to the /api/profiles/client/*
 * endpoints. The access token still lives in the same in-memory slot in
 * api/client.js — fine in practice because a single browser tab is ever
 * one audience at a time (staff master dashboard XOR client dashboard),
 * never both.
 */
export function ClientAuthProvider({ children }) {
  const [clientUser, setClientUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const clearAuth = useCallback(() => {
    setAccessToken(null)
    setClientUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(clearAuth)
    setRefreshEndpoint('/profiles/client/refresh')
    clientRefresh()
      .then((data) => {
        setAccessToken(data.access_token)
        setClientUser(data.client)
      })
      .catch(() => {
        setAccessToken(null)
        setClientUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await clientLogin(email, password)
    setAccessToken(data.access_token)
    setClientUser(data.client)
    return data
  }, [])

  const logout = useCallback(async () => {
    try {
      await clientLogout()
    } finally {
      clearAuth()
    }
  }, [clearAuth])

  const value = useMemo(
    () => ({ clientUser, loading, isAuthenticated: !!clientUser, login, logout }),
    [clientUser, loading, login, logout]
  )

  return <ClientAuthContext.Provider value={value}>{children}</ClientAuthContext.Provider>
}

export function useClientAuth() {
  const ctx = useContext(ClientAuthContext)
  if (!ctx) throw new Error('useClientAuth must be used within ClientAuthProvider')
  return ctx
}
