import React from 'react'

// Stands in for the (up to) 4 translator bot participants that live_translation.py
// runs per meeting — those are filtered out of the video grid entirely (see
// CallLayout.jsx), so this is the only visible sign live translation is
// active, collapsing however many bots are actually connected into one.
// Reuses the app-wide .badge system (theme/tokens.css) rather than one-off
// styling — badge-agent (green) reads as "a service is running", and
// badge-pulse gives it a subtle "live" cue.
export default function TranslationIndicator({ active }) {
  if (!active) return null

  return (
    <div className="cq-translation-indicator" role="status">
      <span className="badge badge-agent badge-pulse">Live translation</span>
    </div>
  )
}
