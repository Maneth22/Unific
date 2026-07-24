import React, { useState } from 'react'
import CostDashboardTab from './CostDashboardTab'
import RegistryPanel from './RegistryPanel'
import FinancialDashboard from './FinancialDashboard'
import ApiMonitorPanel from './ApiMonitorPanel'
import CalendarView from './CalendarView'
import ArchiveLocker from './ArchiveLocker'
import AiUsagePanel from './AiUsagePanel'

const TABS = [
  { key: 'dashboard', label: 'Dashboard', Component: CostDashboardTab },
  { key: 'registry', label: 'Account Registry', Component: RegistryPanel },
  { key: 'financial', label: 'Financial Dashboard', Component: FinancialDashboard },
  { key: 'ai-usage', label: 'AI Usage', Component: AiUsagePanel },
  { key: 'api-monitor', label: 'API Monitor', Component: ApiMonitorPanel },
  { key: 'calendar', label: 'Calendar', Component: CalendarView },
  { key: 'archive', label: 'Archive Locker', Component: ArchiveLocker },
]

export default function AccountsRoomHome() {
  const [tab, setTab] = useState('dashboard')
  const Active = TABS.find((t) => t.key === tab).Component

  return (
    <div>
      <h1 style={{ fontSize: 20, margin: '10px 0 4px' }}>Accounts Room</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        The internal control centre for every account, subscription, payment, and asset UNIFIC
        uses. Internal only — no member reaches this room.
      </p>

      <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--line)', marginBottom: 20 }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              border: 'none',
              background: 'none',
              padding: '10px 14px',
              fontSize: 13,
              fontWeight: 700,
              cursor: 'pointer',
              color: tab === t.key ? 'var(--token)' : 'var(--sub)',
              borderBottom: tab === t.key ? '2px solid var(--token)' : '2px solid transparent',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <Active />
    </div>
  )
}
