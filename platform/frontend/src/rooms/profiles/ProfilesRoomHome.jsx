import React, { useState } from 'react'
import IdentityTree from './IdentityTree'
import PermissionsEditor from './PermissionsEditor'
import ProfileAccountPanel from './ProfileAccountPanel'
import ConsentPanel from './ConsentPanel'
import AiUsageDetail from './AiUsageDetail'
import StaffDirectoryPanel from './StaffDirectoryPanel'
import CreateClientOrgForm from './CreateClientOrgForm'
import OrgProfilePanel from './OrgProfilePanel'

const TABS = [
  { key: 'org-profile', label: 'Org / ILC Profile', Component: OrgProfilePanel },
  { key: 'permission', label: 'Permissions', Component: PermissionsEditor },
  { key: 'account', label: 'Profile Account', Component: ProfileAccountPanel },
  { key: 'consent', label: 'Consent', Component: ConsentPanel },
  { key: 'ai-usage', label: 'AI Usage', Component: AiUsageDetail },
]

// Clients (the identity tree) and Staff are deliberately two separate
// top-level views here — never mixed in one list, so the admin can't
// confuse a client org/community/member with a UNIFIC staff account.
const TOP_TABS = [
  { key: 'clients', label: 'Clients' },
  { key: 'staff', label: 'Staff' },
]

export default function ProfilesRoomHome() {
  const [topTab, setTopTab] = useState('clients')
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('org-profile')
  const [treeRefreshKey, setTreeRefreshKey] = useState(0)

  return (
    <div>
      <h1 style={{ fontSize: 20, margin: '10px 0 4px' }}>Profiles Room</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        The registry of every ID and its permissions. Every message passes through here first,
        checked against the registry, before it reaches the Meeting Room.
      </p>

      <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--line)', marginBottom: 20 }}>
        {TOP_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTopTab(t.key)}
            style={{
              border: 'none', background: 'none', padding: '10px 14px', fontSize: 14, fontWeight: 800, cursor: 'pointer',
              color: topTab === t.key ? 'var(--token)' : 'var(--sub)',
              borderBottom: topTab === t.key ? '2px solid var(--token)' : '2px solid transparent',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {topTab === 'staff' ? (
        <StaffDirectoryPanel />
      ) : (
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
          <div style={{ width: 320, flexShrink: 0 }}>
            <CreateClientOrgForm onCreated={() => setTreeRefreshKey((k) => k + 1)} />
            <IdentityTree key={treeRefreshKey} selectedId={selectedId} onSelect={setSelectedId} />
          </div>

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
      )}
    </div>
  )
}
