import React from 'react'
import { Loader2 } from 'lucide-react'

const VARIANT_CLASS = {
  primary: 'btn btn-primary',
  danger: 'btn btn-danger',
  secondary: 'btn',
}

// Thin wrapper over the existing .btn/.btn-primary/.btn-danger classes
// (theme/tokens.css) — every page that already uses those classes directly
// keeps working unchanged; this just adds disabled/loading handling so new
// pages don't hand-roll it.
export default function Button({
  variant = 'secondary',
  loading = false,
  disabled = false,
  icon: Icon,
  className = '',
  children,
  ...rest
}) {
  return (
    <button
      className={`${VARIANT_CLASS[variant] || VARIANT_CLASS.secondary} ${className}`.trim()}
      disabled={disabled || loading}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, ...rest.style }}
      {...rest}
    >
      {loading ? <Loader2 size={14} className="ui-spin" /> : Icon ? <Icon size={14} /> : null}
      {children}
    </button>
  )
}
