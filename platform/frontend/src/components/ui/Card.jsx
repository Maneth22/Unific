import React from 'react'

// Thin wrapper over the existing .card class (theme/tokens.css) with a
// consistent padding prop — the class itself stays usable directly
// anywhere it already is.
export default function Card({ padding = 20, className = '', style, children, ...rest }) {
  return (
    <div className={`card ${className}`.trim()} style={{ padding, ...style }} {...rest}>
      {children}
    </div>
  )
}
