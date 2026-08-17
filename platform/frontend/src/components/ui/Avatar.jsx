import React from 'react'

function initialsFor(name) {
  if (!name) return '?'
  const parts = String(name).trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

// Initials-based circular avatar — same visual idea as the video-call
// tiles' .cq-tile-avatar (see components/video-call/ParticipantTileBody.jsx),
// reused here for the sidebar footer / Topbar avatar rather than
// reinventing it.
export default function Avatar({ name, size = 32, style, ...rest }) {
  return (
    <span
      className="ui-avatar"
      style={{ width: size, height: size, fontSize: Math.max(10, size * 0.4), ...style }}
      aria-hidden="true"
      {...rest}
    >
      {initialsFor(name)}
    </span>
  )
}
