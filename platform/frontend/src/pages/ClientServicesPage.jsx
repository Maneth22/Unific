import React, { useEffect, useState } from 'react'
import { useClientAuth } from '../context/ClientAuthContext'
import { getAccountsOverview } from '../api/clientProfiles'

// Future add-on services (agriculture chatbots, document translation, etc.)
// are explicitly not built yet — this is the placeholder foundation the
// client can see, not a working marketplace.
const COMING_SOON = [
  { name: 'Agriculture instruction chatbot', kind: 'AI assistant for ILC members' },
  { name: 'Document translation', kind: 'Translate registrations & forms' },
]

export default function ClientServicesPage() {
  const { isOwner } = useClientAuth()
  const [providers, setProviders] = useState(null)

  useEffect(() => {
    if (isOwner) getAccountsOverview().then((o) => setProviders(o.service_providers))
  }, [isOwner])

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Services</h1>
      <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
        The services your organization currently uses, and what's coming next.
      </p>

      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>Currently in use</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12, marginBottom: 24 }}>
        {(providers || [
          { name: 'Google Gemini', kind: 'AI language model', model: '—', status: 'active' },
          { name: 'WhatsApp', kind: 'Messaging', model: '—', status: 'active' },
        ]).map((p) => (
          <div key={p.name} className="card" style={{ padding: 14 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{p.name}</div>
            <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 8 }}>{p.kind}</div>
            <span className={`badge ${p.status === 'active' ? 'badge-agent' : 'badge-pending'}`}>{p.status}</span>
          </div>
        ))}
      </div>

      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>Available soon</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
        {COMING_SOON.map((s) => (
          <div key={s.name} className="card" style={{ padding: 14, opacity: 0.7 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{s.name}</div>
            <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 8 }}>{s.kind}</div>
            <span className="badge badge-room">coming soon</span>
          </div>
        ))}
      </div>
    </div>
  )
}
