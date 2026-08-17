import React from 'react'

// Shape primitives for loading states. Most pages today have no loading
// state at all (bare "Loading…" text or nothing) — this is purely additive
// wherever it's adopted, it never changes a page's data-fetching.
export function SkeletonLine({ width = '100%', height = 12, style }) {
  return <div className="ui-skeleton" style={{ width, height, ...style }} />
}

export function SkeletonBlock({ width = '100%', height = 80, style }) {
  return <div className="ui-skeleton" style={{ width, height, borderRadius: 'var(--radius)', ...style }} />
}

export function SkeletonAvatar({ size = 36, style }) {
  return <div className="ui-skeleton" style={{ width: size, height: size, borderRadius: '999px', ...style }} />
}
