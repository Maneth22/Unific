import { useEffect, useRef } from 'react'

// Internal staff/admin + vetted client-org users, not a walk-up public
// flow, and the app handles account/financial + community-member data —
// 30 minutes is a reasonable middle ground (tighter than a typical
// low-sensitivity SaaS default, not so aggressive it interrupts someone
// reading a long thread). Exported so callers can override per-audience if
// ever needed.
export const IDLE_TIMEOUT_MS = 30 * 60 * 1000

/**
 * Auto-logout after a period of no user activity. Only ticks while
 * `enabled` is true (pass the session's isAuthenticated flag) — there's
 * nothing to protect for a logged-out visitor, and flipping to false tears
 * every listener down via the effect's cleanup.
 *
 * `onIdle` is read through a ref so the effect doesn't need to re-subscribe
 * every render just because it's a new closure (e.g. over `logout`/
 * `navigate`) — the effect's own dependency array only needs to change
 * when the timing parameters themselves change.
 */
export default function useIdleLogout(enabled, timeoutMs = IDLE_TIMEOUT_MS, onIdle, throttleMs = 5000) {
  const onIdleRef = useRef(onIdle)
  const timerRef = useRef(null)
  const lastResetRef = useRef(0)

  useEffect(() => {
    onIdleRef.current = onIdle
  }, [onIdle])

  useEffect(() => {
    if (!enabled) return undefined

    const clear = () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    const arm = () => {
      timerRef.current = setTimeout(() => onIdleRef.current?.(), timeoutMs)
    }

    const onActivity = () => {
      const now = Date.now()
      // Throttle: mousemove/scroll can fire dozens of times a second —
      // only actually reset the timer at most once per throttleMs.
      if (now - lastResetRef.current < throttleMs) return
      lastResetRef.current = now
      clear()
      arm()
    }

    arm()
    const events = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll']
    events.forEach((evt) => window.addEventListener(evt, onActivity, { passive: true }))

    return () => {
      clear()
      events.forEach((evt) => window.removeEventListener(evt, onActivity))
    }
  }, [enabled, timeoutMs, throttleMs])
}
