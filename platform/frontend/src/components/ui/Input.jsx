import React from 'react'

// Label-above-field input — replaces the independently-duplicated inline
// input style={{}} objects across ~15+ form-bearing pages. Purely
// presentational: value/onChange/name/type etc. all pass straight through
// via {...rest}, so existing form-handling logic is untouched wherever
// this gets adopted.
export default function Input({ label, error, id, className = '', containerStyle, ...rest }) {
  const inputId = id || rest.name
  return (
    <div className="ui-field" style={containerStyle}>
      {label && (
        <label className="ui-field-label" htmlFor={inputId}>
          {label}
        </label>
      )}
      <input id={inputId} className={`ui-input ${className}`.trim()} {...rest} />
      {error && <span className="ui-field-error">{error}</span>}
    </div>
  )
}
