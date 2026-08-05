import React from 'react'

// Generic fallback for uncaught render exceptions, rendered by
// ErrorBoundary in main.jsx — which wraps <App/> itself, so this renders
// OUTSIDE any router context. Plain <a> tags only, no <Link>/useNavigate.
export default function ErrorPage() {
  return (
    <div className="error-page-wrap">
      <div className="card error-page-card">
        <div className="error-page-icon" style={{ color: 'var(--red)' }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 3l10 18H2L12 3z" strokeLinejoin="round" />
            <line x1="12" y1="9" x2="12" y2="14" />
            <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
          </svg>
        </div>
        <h1>Something went wrong</h1>
        <p>An unexpected error occurred. Reloading the page usually fixes it.</p>
        <div className="error-page-actions">
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
            Reload page
          </button>
          <a href="/" className="btn">Go home</a>
        </div>
      </div>
    </div>
  )
}
