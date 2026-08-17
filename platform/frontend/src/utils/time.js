// Same Intl.RelativeTimeFormat pattern already used independently in
// MeetingScheduler.jsx / ClientMeetingRoomPage.jsx — extracted here so the
// Dashboard's merged activity feed doesn't declare a third copy.
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

export function relativeTime(iso) {
  if (!iso) return ''
  const diffMs = new Date(iso) - Date.now()
  const abs = Math.abs(diffMs)
  const minute = 60000
  const hour = 3600000
  const day = 86400000
  if (abs < minute) return 'just now'
  if (abs < hour) return rtf.format(Math.round(diffMs / minute), 'minute')
  if (abs < day) return rtf.format(Math.round(diffMs / hour), 'hour')
  return rtf.format(Math.round(diffMs / day), 'day')
}
