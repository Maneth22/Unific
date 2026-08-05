import React from 'react'
import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="error-page-wrap">
      <div className="card error-page-card">
        <div className="error-page-icon" style={{ color: 'var(--sub)' }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="9" />
            <path d="M9.5 9a2.5 2.5 0 0 1 4.5 1.5c0 1.5-2 2-2 3.5" strokeLinecap="round" />
            <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
          </svg>
        </div>
        <h1>Page not found</h1>
        <p>The page you're looking for doesn't exist or may have moved.</p>
        <div className="error-page-actions">
          <Link to="/" className="btn btn-primary">Back home</Link>
        </div>
      </div>
    </div>
  )
}
