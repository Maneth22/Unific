import { useCallback, useEffect, useState } from 'react'
import { BREAKPOINTS } from './breakpoints'

const STORAGE_KEY = 'sidebar:collapsed'

function readStoredCollapsed() {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function writeStoredCollapsed(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
  } catch {
    // ignore (private browsing / storage disabled)
  }
}

function getMode(mobileQuery, tabletQuery) {
  if (mobileQuery.matches) return 'mobile'
  if (tabletQuery.matches) return 'tablet'
  return 'desktop'
}

// Owns all sidebar responsive/interaction state:
// - mode: which breakpoint tier we're in ('mobile' | 'tablet' | 'desktop')
// - collapsed: desktop/tablet slim-tab state (persisted for desktop only;
//   tablet always forces collapsed=true on entry)
// - mobileOpen: whether the mobile overlay drawer is open
export function useCollapsibleSidebar() {
  const [mode, setMode] = useState('desktop')
  const [collapsed, setCollapsed] = useState(() => readStoredCollapsed())
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const mobileQuery = window.matchMedia(`(max-width: ${BREAKPOINTS.mobile}px)`)
    const tabletQuery = window.matchMedia(
      `(min-width: ${BREAKPOINTS.mobile + 1}px) and (max-width: ${BREAKPOINTS.tablet}px)`
    )

    const applyMode = () => setMode(getMode(mobileQuery, tabletQuery))
    applyMode()

    mobileQuery.addEventListener('change', applyMode)
    tabletQuery.addEventListener('change', applyMode)
    return () => {
      mobileQuery.removeEventListener('change', applyMode)
      tabletQuery.removeEventListener('change', applyMode)
    }
  }, [])

  useEffect(() => {
    if (mode === 'tablet') {
      setCollapsed(true)
    } else if (mode === 'desktop') {
      setCollapsed(readStoredCollapsed())
    } else if (mode === 'mobile') {
      setMobileOpen(false)
    }
  }, [mode])

  useEffect(() => {
    if (!mobileOpen) return undefined
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setMobileOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [mobileOpen])

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      if (mode === 'desktop') writeStoredCollapsed(next)
      return next
    })
  }, [mode])

  const openMobile = useCallback(() => setMobileOpen(true), [])
  const closeMobile = useCallback(() => setMobileOpen(false), [])

  return { mode, collapsed, mobileOpen, toggleCollapsed, openMobile, closeMobile }
}
