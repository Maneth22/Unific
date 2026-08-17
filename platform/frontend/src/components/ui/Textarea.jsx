import React from 'react'

export default function Textarea({ label, error, id, className = '', containerStyle, ...rest }) {
  const areaId = id || rest.name
  return (
    <div className="ui-field" style={containerStyle}>
      {label && (
        <label className="ui-field-label" htmlFor={areaId}>
          {label}
        </label>
      )}
      <textarea id={areaId} className={`ui-textarea ${className}`.trim()} {...rest} />
      {error && <span className="ui-field-error">{error}</span>}
    </div>
  )
}
