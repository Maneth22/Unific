import React, { useState } from 'react'
import ConversationsView from './ConversationsView'
import WebhookLogView from './WebhookLogView'

const TABS = [
  { key: 'conversations', label: 'Conversations', Component: ConversationsView },
  { key: 'webhook_log', label: 'Webhook Log', Component: WebhookLogView },
]

// Purpose-built QA surface: "did a WhatsApp message actually work" —
// combines Meeting Room's per-identity conversation viewer (translation,
// tone analysis, auto-reply mode) with the raw webhook log (catches
// messages that never became a conversation at all: unlinked number,
// gate/charge block, malformed payload). Deliberately separate from
// Meeting Room's Chat tab, which stays the operational reply tool.
export default function WhatsAppMessagesHome() {
  const [tab, setTab] = useState('conversations')
  const Active = TABS.find((t) => t.key === tab).Component

  return (
    <div>
      <h1 style={{ fontSize: 20, margin: '10px 0 4px' }}>WhatsApp Messages</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        Check what actually came through WhatsApp and how the interface handled it — conversations
        (with translation/tone detail) plus the raw webhook log for anything that got rejected
        before it ever became a conversation.
      </p>

      <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--line)', marginBottom: 20, overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
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
