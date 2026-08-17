import React, { useEffect, useRef, useState } from 'react'
import { Bell, ChevronDown, LogOut, Search } from 'lucide-react'
import Avatar from '../../components/ui/Avatar.jsx'

// Mounted inside AppShell.jsx as the first child of <main>, above whatever
// page content the route renders. Search is visual-only in this pass (see
// the redesign plan §3) — no query state, no results, nothing wired to any
// endpoint. Notification bell is likewise a static affordance (no
// notifications backend exists yet). The avatar dropdown is the one real
// piece of behavior here, and it reuses the same logout() the sidebar
// footer already calls — this is a second entry point to the same action,
// not a second source of truth.
export default function Topbar({ user, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return
    const onDocClick = (e) => {
      if (!rootRef.current?.contains(e.target)) setMenuOpen(false)
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  if (!user) return null

  return (
    <div className="app-topbar-bar">
      <label className="app-topbar-search">
        <Search size={15} aria-hidden="true" />
        <input type="text" placeholder="Search anything…" aria-label="Search" disabled />
      </label>

      <div className="app-topbar-actions" ref={rootRef}>
        <button type="button" className="app-topbar-icon-btn" aria-label="Notifications">
          <Bell size={17} />
        </button>

        <button
          type="button"
          className="app-topbar-avatar-btn"
          onClick={() => setMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <Avatar name={user.name} size={30} />
          <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', lineHeight: 1.25 }}>
            <span>{user.name}</span>
            {user.subtitle && (
              <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--sub)' }}>{user.subtitle}</span>
            )}
          </span>
          <ChevronDown size={14} />
        </button>

        {menuOpen && (
          <div className="app-topbar-menu" role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false)
                onLogout?.()
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <LogOut size={14} /> Log out
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
