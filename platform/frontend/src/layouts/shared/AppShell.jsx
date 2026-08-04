import React, { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { useCollapsibleSidebar } from './useCollapsibleSidebar'

// Active/inactive NavLink styling — lifted verbatim from the nav links
// that used to be duplicated across the three *Layout.jsx files.
function navLinkStyle({ isActive }) {
  return {
    padding: '9px 10px',
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    textDecoration: 'none',
    color: isActive ? 'white' : 'var(--ink)',
    background: isActive ? 'var(--slate)' : 'transparent',
  }
}

// Shared shell for the three sidebar layouts (staff admin, staff portal,
// client portal). Handles the collapsible-sidebar / responsive-drawer
// chrome; brand, nav items, and footer content stay data supplied by
// each caller so auth wiring stays in the individual layout files.
//
// navItems: { key, to, label, end?, dividerBefore? }[]
export default function AppShell({ brand, navItems, footer, children }) {
  const { mode, collapsed, mobileOpen, toggleCollapsed, openMobile, closeMobile } =
    useCollapsibleSidebar()
  const asideRef = useRef(null)
  const hamburgerRef = useRef(null)

  // Simple focus management for the mobile drawer: move focus in when it
  // opens, return it to the hamburger button when it closes.
  useEffect(() => {
    if (mode === 'mobile' && mobileOpen) {
      asideRef.current?.focus()
    } else if (mode === 'mobile' && !mobileOpen) {
      hamburgerRef.current?.focus()
    }
  }, [mode, mobileOpen])

  // Keep keyboard focus within the open drawer (Tab/Shift+Tab wrap).
  const onDrawerKeyDown = (e) => {
    if (e.key !== 'Tab' || mode !== 'mobile' || !mobileOpen) return
    const focusable = asideRef.current?.querySelectorAll(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
    if (!focusable || focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const asideClassName = [
    'app-sidebar',
    mode === 'mobile' ? 'app-sidebar--drawer' : '',
    mode !== 'mobile' && collapsed ? 'app-sidebar--collapsed' : '',
    mode === 'mobile' && mobileOpen ? 'app-sidebar--open' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="app-shell">
      {mode === 'mobile' && (
        <div className="app-topbar">
          <button
            ref={hamburgerRef}
            className="app-hamburger"
            aria-label="Open navigation"
            onClick={openMobile}
          >
            ☰
          </button>
          <div style={{ fontWeight: 800, fontSize: 15 }}>{brand}</div>
        </div>
      )}

      {mode === 'mobile' && mobileOpen && (
        <div className="app-overlay" onClick={closeMobile} aria-hidden="true" />
      )}

      <aside
        ref={asideRef}
        className={asideClassName}
        tabIndex={mode === 'mobile' ? -1 : undefined}
        role={mode === 'mobile' ? 'dialog' : undefined}
        aria-modal={mode === 'mobile' ? mobileOpen : undefined}
        aria-label="Main navigation"
        onKeyDown={onDrawerKeyDown}
      >
        {mode === 'mobile' && (
          <button className="app-sidebar-close" aria-label="Close navigation" onClick={closeMobile}>
            ×
          </button>
        )}

        <div className="app-sidebar-brand" style={{ fontWeight: 800, fontSize: 15, padding: '0 8px 18px' }}>
          {brand}
        </div>

        <nav className="app-sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.key}
              to={item.to}
              end={item.end}
              onClick={() => mode === 'mobile' && closeMobile()}
              style={(state) => ({
                ...navLinkStyle(state),
                ...(item.dividerBefore ? { marginTop: 10 } : {}),
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="app-sidebar-footer">{footer}</div>

        {mode !== 'mobile' && (
          <button
            className="app-sidebar-tab"
            aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            onClick={toggleCollapsed}
          >
            {collapsed ? '›' : '‹'}
          </button>
        )}
      </aside>

      <main className="app-main">{children}</main>
    </div>
  )
}
