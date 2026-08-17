import React, { createContext, useCallback, useContext, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Info } from 'lucide-react'

const ToastContext = createContext(null)

const ICON_BY_VARIANT = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

// The one genuinely new app-wide piece of state this redesign introduces
// (see plan §2) — mounted once, alongside (never in place of) the existing
// AuthProvider/ClientAuthProvider. Existing inline badge-agent/badge-alert
// success/error blocks stay exactly as-is on every page that hasn't been
// converted; this is only additive for pages that choose to use it.
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const idRef = useRef(0)

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (message, variant = 'info', duration = 4000) => {
      const id = ++idRef.current
      setToasts((list) => [...list, { id, message, variant }])
      if (duration > 0) {
        setTimeout(() => dismiss(id), duration)
      }
      return id
    },
    [dismiss]
  )

  return (
    <ToastContext.Provider value={{ push, dismiss }}>
      {children}
      <div className="ui-toast-viewport" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICON_BY_VARIANT[t.variant] || Info
          return (
            <div key={t.id} className={`ui-toast ui-toast--${t.variant}`} role="status">
              <Icon size={16} className="ui-toast-icon" />
              <span>{t.message}</span>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

// useToast().push('Saved', 'success') / .push('Something failed', 'error')
export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast() must be used within <ToastProvider>')
  return ctx
}
