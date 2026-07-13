import React, { useState } from 'react'
import IdentityTree from './IdentityTree'
import PermissionsEditor from './PermissionsEditor'
import ProfileAccountPanel from './ProfileAccountPanel'
import ConsentPanel from './ConsentPanel'
import AiUsageDetail from './AiUsageDetail'

const TABS = [
  { key: 'permission', label: 'Permissions', Component: PermissionsEditor },
  { key: 'account', label: 'Profile Account', Component: ProfileAccountPanel },
  { key: 'consent', label: 'Consent', Component: ConsentPanel },
  { key: 'ai-usage', label: 'AI Usage', Component: AiUsageDetail },
]

export default function ProfilesRoomHome() {
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('permission')

  return (
    <div>
      <h1 style={{ fontSize: 20, margin: '10px 0 4px' }}>Profiles Room</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        The registry of every ID and its permissions. Every message passes through here first,
        checked against the registry, before it reaches the Meeting Room.
      </p>

      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
        <IdentityTree selectedId={selectedId} onSelect={setSelectedId} />

        <div style={{ flex: 1 }}>
          {!selectedId ? (
            <div className="card" style={{ padding: 24, color: 'var(--sub)' }}>
              Select or create an identity to view its permissions, account, and consent records.
            </div>
          ) : (
            <>
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
              {TABS.map(({ key, Component }) => key === tab && <Component key={key} identityId={selectedId} />)}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
