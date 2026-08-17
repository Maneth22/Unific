import React from 'react'

export default function Select({ label, error, id, className = '', containerStyle, children, ...rest }) {
  const selectId = id || rest.name
  return (
    <div className="ui-field" style={containerStyle}>
      {label && (
        <label className="ui-field-label" htmlFor={selectId}>
          {label}
        </label>
      )}
      <select id={selectId} className={`ui-select ${className}`.trim()} {...rest}>
        {children}
      </select>
      {error && <span className="ui-field-error">{error}</span>}
    </div>
  )
}
