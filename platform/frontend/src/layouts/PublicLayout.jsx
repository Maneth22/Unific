import React, { useState } from 'react'
import { Link, Outlet } from 'react-router-dom'
import logo from '../assets/logo.png'

// Simple top-nav marketing layout for the public site (landing/about/
// contact) — deliberately not built on the sidebar AppShell used for the
// authenticated dashboards, since this is a different shape of nav
// entirely. No auth provider is mounted anywhere in this tree.
export default function PublicLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div>
      <header className="public-nav">
        <Link
          to="/"
          className="public-nav-brand"
          onClick={() => setMobileOpen(false)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
        >
          <img src={logo} alt="" width={28} height={28} style={{ display: 'block' }} />
          UNIFIC <span style={{ color: 'var(--token)' }}>Platform</span>
        </Link>

        <nav className="public-nav-links">
          <Link to="/about">About</Link>
          <Link to="/contact">Contact</Link>
        </nav>

        <div className="public-nav-actions">
          <Link to="/support/login" className="public-nav-supporter-link">
            Staff &amp; Partners
          </Link>
          <Link to="/login" className="btn btn-primary">
            Log in
          </Link>
        </div>

        <button
          className="public-hamburger"
          aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMobileOpen((v) => !v)}
        >
          {mobileOpen ? '×' : '☰'}
        </button>
      </header>

      <div className={`public-mobile-menu ${mobileOpen ? 'public-mobile-menu--open' : ''}`}>
        <Link to="/about" onClick={() => setMobileOpen(false)}>About</Link>
        <Link to="/contact" onClick={() => setMobileOpen(false)}>Contact</Link>
        <Link to="/support/login" onClick={() => setMobileOpen(false)}>Staff &amp; Partners</Link>
      </div>

      <main className="public-main">
        <Outlet />
      </main>

      <footer className="public-footer">
        <div>© {new Date().getFullYear()} UNIFIC. All rights reserved.</div>
        <div className="public-footer-links">
          <Link to="/about">About</Link>
          <Link to="/contact">Contact</Link>
          <Link to="/login">Log in</Link>
          <Link to="/support/login">Staff &amp; Partners</Link>
        </div>
      </footer>
    </div>
  )
}
