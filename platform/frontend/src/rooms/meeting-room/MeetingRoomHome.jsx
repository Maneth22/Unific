import React, { useState } from 'react'
import ChatView from './ChatView'
import ConfigBoard from './ConfigBoard'
import MeetingScheduler from './MeetingScheduler'
import ArchiveLocker from './ArchiveLocker'
import WhatsAppLinks from './WhatsAppLinks'

const TABS = [
  { key: 'chat', label: 'Chat', Component: ChatView },
  { key: 'meetings', label: 'Meetings', Component: MeetingScheduler },
  { key: 'config', label: 'Config Board', Component: ConfigBoard },
  { key: 'archive', label: 'Archive Locker', Component: ArchiveLocker },
  { key: 'links', label: 'WhatsApp Links', Component: WhatsAppLinks },
]

export default function MeetingRoomHome() {
  const [tab, setTab] = useState('chat')
  const Active = TABS.find((t) => t.key === tab).Component

  return (
    <div>
      <h1 style={{ fontSize: 20, margin: '10px 0 4px' }}>Meeting Room</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        Renamed from Communications — the only room that replies. Runs the chat, the weekly
        meeting, and the translation, adapted to reach community members through WhatsApp.
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
