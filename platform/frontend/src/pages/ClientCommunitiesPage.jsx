import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { createCommunity, listCommunities, regenerateInvite } from '../api/clientProfiles'
import { useClientAuth } from '../context/ClientAuthContext'

export default function ClientCommunitiesPage() {
  const { clientUser } = useClientAuth()
  const [communities, setCommunities] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [copiedId, setCopiedId] = useState('')
  const [busyId, setBusyId] = useState('')

  async function refresh() {
    setCommunities(await listCommunities())
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      await createCommunity(name, clientUser.identity_id)
      setName('')
      setShowCreate(false)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create the community group')
    }
  }

  async function handleRegenerate(groupId) {
    setBusyId(groupId)
    try {
      await regenerateInvite(groupId)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not regenerate the invite link')
    } finally {
      setBusyId('')
    }
  }

  async function handleCopy(url, id) {
    try {
      await navigator.clipboard.writeText(url)
      setCopiedId(id)
      setTimeout(() => setCopiedId(''), 1500)
    } catch {
      // Clipboard access can be denied — the URL is still visible to copy manually.
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>Communities</h1>
          <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
            Each community has its own registration link — share it and members register
            themselves, then get redirected straight into WhatsApp with their personal agent.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? 'Cancel' : '+ Create community group'}
        </button>
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      {showCreate && (
        <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'flex', gap: 8 }}>
          <input
            required
            placeholder="e.g. Sandahkal Group India"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: 1, padding: 8, border: '1px solid var(--line)', borderRadius: 8 }}
          />
          <button type="submit" className="btn btn-primary">Create</button>
        </form>
      )}

      {communities.length === 0 ? (
        <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>No community groups yet — create one above.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
          {communities.map((c) => (
            <div key={c.id} className="card" style={{ padding: 16 }}>
              <Link to={`/client/communities/${c.id}`} style={{ textDecoration: 'none', color: 'var(--ink)' }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>{c.name}</div>
              </Link>
              <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 10 }}>
                {c.member_count} member{c.member_count === 1 ? '' : 's'}
              </div>

              {c.invite ? (
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input
                    readOnly
                    value={c.invite.invite_url}
                    onFocus={(e) => e.target.select()}
                    style={{ flex: 1, padding: 6, fontSize: 11, border: '1px solid var(--line)', borderRadius: 6 }}
                  />
                  <button className="btn" style={{ fontSize: 11, padding: '6px 8px' }} onClick={() => handleCopy(c.invite.invite_url, c.id)}>
                    {copiedId === c.id ? 'Copied' : 'Copy'}
                  </button>
                </div>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--sub)' }}>No active invite link.</div>
              )}
              <button
                className="btn"
                style={{ marginTop: 8, fontSize: 11 }}
                disabled={busyId === c.id}
                onClick={() => handleRegenerate(c.id)}
              >
                {busyId === c.id ? 'Regenerating…' : 'Regenerate link'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
