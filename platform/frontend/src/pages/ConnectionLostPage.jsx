import React from 'react'

// Shown when the app's initial silent-refresh call fails with a genuine
// network error (no response at all) rather than a normal 401 "not logged
// in yet" — see AuthContext/ClientAuthContext's `connectionError` state and
// App.jsx's StaffAreaGate/ClientAreaGate.
export default function ConnectionLostPage() {
  return (
    <div className="error-page-wrap">
      <div className="card error-page-card">
        <div className="error-page-icon" style={{ color: 'var(--amber)' }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M4 4l16 16" strokeLinecap="round" />
            <path d="M9 9a5 5 0 0 1 7.5 1.5" strokeLinecap="round" />
            <path d="M6 12a8 8 0 0 1 2-2.2" strokeLinecap="round" />
            <path d="M3 9a12 12 0 0 1 3-2.3" strokeLinecap="round" />
            <circle cx="12" cy="18" r="1" fill="currentColor" stroke="none" />
          </svg>
        </div>
        <h1>Can't reach the server</h1>
        <p>It looks like the connection dropped, or the server is temporarily unavailable. Check your connection and try again.</p>
        <div className="error-page-actions">
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      </div>
    </div>
  )
}
