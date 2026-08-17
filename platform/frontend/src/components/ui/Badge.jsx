import React from 'react'

// Consolidates the STATUS_BADGE/HEALTH_BADGE-style class maps that today
// are each independently re-declared per page (13+ files) into one typed
// `status` prop over the existing badge/badge-* classes (theme/tokens.css).
// Pages with genuinely bespoke status sets can keep their own map and pass
// `variant` directly instead of `status` — this doesn't remove that
// flexibility, it just gives the common cases a shared home.
const STATUS_VARIANT = {
  active: 'agent',
  success: 'agent',
  approved: 'agent',
  online: 'agent',
  healthy: 'agent',
  pending: 'pending',
  waiting: 'pending',
  degraded: 'pending',
  error: 'alert',
  failed: 'alert',
  rejected: 'alert',
  offline: 'alert',
  inactive: 'room',
  info: 'id',
  account: 'account',
}

export default function Badge({ status, variant, pulse = false, className = '', children, ...rest }) {
  const resolved = variant || STATUS_VARIANT[String(status).toLowerCase()] || 'room'
  return (
    <span
      className={`badge badge-${resolved} ${pulse ? 'badge-pulse' : ''} ${className}`.trim()}
      {...rest}
    >
      {children ?? status}
    </span>
  )
}
