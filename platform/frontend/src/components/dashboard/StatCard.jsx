import React from 'react'
import Card from '../ui/Card.jsx'

// label + big number + optional trend line + icon slot — used by the
// Dashboard's 4 KPI cards (StaffHomePage.jsx). `trend` is an already-
// formatted string (e.g. "+12% from last month") composed by the caller
// from real data; this component never fabricates a percentage itself —
// pass null/undefined when the underlying list has no usable timestamp.
export default function StatCard({ label, value, trend, icon: Icon }) {
  return (
    <Card className="stat-card" padding={undefined}>
      <div className="stat-card-top">
        <span className="stat-card-label">{label}</span>
        {Icon && (
          <span className="stat-card-icon">
            <Icon size={16} />
          </span>
        )}
      </div>
      <span className="stat-card-value">{value}</span>
      {trend && <span className="stat-card-trend stat-card-trend--up">{trend}</span>}
    </Card>
  )
}
