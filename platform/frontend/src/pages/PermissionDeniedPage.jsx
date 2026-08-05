import React from 'react'
import { Link } from 'react-router-dom'

// Reached at /403 — RequireAdmin's redirect target for a signed-in but
// non-admin staff account. The real boundary is still server-side
// (require_admin on every request); this is just a friendlier client-side
// signal of the same boundary instead of a silent bounce.
export default function PermissionDeniedPage() {
  return (
    <div className="error-page-wrap">
      <div className="card error-page-card">
        <div className="error-page-icon" style={{ color: 'var(--red)' }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="5" y="11" width="14" height="9" rx="2" />
            <path d="M8 11V7a4 4 0 0 1 8 0v4" />
          </svg>
        </div>
        <h1>You don't have access to this page</h1>
        <p>Your account doesn't have admin-tier access. If you think this is a mistake, ask an admin to check your staff account.</p>
        <div className="error-page-actions">
          <Link to="/portal" className="btn btn-primary">Back to my portal</Link>
        </div>
      </div>
    </div>
  )
}
