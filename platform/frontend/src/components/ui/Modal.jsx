import React, { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

// Genuinely new — nothing like this exists in the codebase today (see the
// redesign plan §2). Focus-trap approach mirrors the one already proven in
// layouts/shared/AppShell.jsx's mobile drawer (Tab/Shift+Tab wrap within
// the panel, Escape/backdrop-click to close, focus moved in on open and
// returned to the triggering element on close).
export default function Modal({ open, onClose, title, children, actions, width = 480 }) {
  const panelRef = useRef(null)
  const triggerRef = useRef(null)

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement
      panelRef.current?.focus()
    } else {
      triggerRef.current?.focus?.()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose?.()
        return
      }
      if (e.key !== 'Tab') return
      const focusable = panelRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
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
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="ui-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div
        ref={panelRef}
        className="ui-modal"
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        tabIndex={-1}
      >
        {title && (
          <div className="ui-modal-header">
            <h2>{title}</h2>
            <button type="button" className="ui-modal-close" aria-label="Close" onClick={onClose}>
              <X size={16} />
            </button>
          </div>
        )}
        {children}
        {actions && <div className="ui-modal-actions">{actions}</div>}
      </div>
    </div>
  )
}
