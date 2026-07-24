import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { createCommunity, listCommunities, regenerateInvite } from '../api/clientProfiles'
import { useClientAuth } from '../context/ClientAuthContext'

const EMPTY_FORM = {
  name: '',
  name_hindi: '',
  registration_number: '',
  date_of_registration: '',
  application_signed: false,
  registered_office: '',
  area_of_operation: '',
  governing_act: '',
  registering_authority: '',
  objective: '',
  cooperative_type: '',
  bank_account: '',
}

export default function ClientCommunitiesPage() {
  const { clientUser } = useClientAuth()
  const [communities, setCommunities] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
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
      await createCommunity({
        ...form,
        parent_id: clientUser.identity_id,
        date_of_registration: form.date_of_registration || null,
      })
      setForm(EMPTY_FORM)
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
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>ILC Communities</h1>
          <p style={{ color: 'var(--sub)', marginBottom: 20 }}>
            Each ILC group has its own registration link and a system-issued Group ID — share the
            link and members register themselves (verified against the roster you set for that
            group), then get redirected straight into WhatsApp with their personal agent.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? 'Cancel' : '+ Create ILC group'}
        </button>
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 14, padding: '8px 12px' }}>{error}</div>}

      {showCreate && (
        <form onSubmit={handleCreate} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8, gridTemplateColumns: '1fr 1fr' }}>
          <input required placeholder="Name (English) — e.g. ILC Sundarkhal" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={inputStyle} />
          <input placeholder="Name (Hindi)" value={form.name_hindi} onChange={(e) => setForm({ ...form, name_hindi: e.target.value })} style={inputStyle} />
          <input placeholder="Registration number" value={form.registration_number} onChange={(e) => setForm({ ...form, registration_number: e.target.value })} style={inputStyle} />
          <input type="date" placeholder="Date of registration" value={form.date_of_registration} onChange={(e) => setForm({ ...form, date_of_registration: e.target.value })} style={inputStyle} />
          <input placeholder="Registered office" value={form.registered_office} onChange={(e) => setForm({ ...form, registered_office: e.target.value })} style={inputStyle} />
          <input placeholder="Area of operation" value={form.area_of_operation} onChange={(e) => setForm({ ...form, area_of_operation: e.target.value })} style={inputStyle} />
          <input placeholder="Governing Act" value={form.governing_act} onChange={(e) => setForm({ ...form, governing_act: e.target.value })} style={inputStyle} />
          <input placeholder="Registering authority" value={form.registering_authority} onChange={(e) => setForm({ ...form, registering_authority: e.target.value })} style={inputStyle} />
          <input placeholder="Cooperative type" value={form.cooperative_type} onChange={(e) => setForm({ ...form, cooperative_type: e.target.value })} style={inputStyle} />
          <input placeholder="Bank account" value={form.bank_account} onChange={(e) => setForm({ ...form, bank_account: e.target.value })} style={inputStyle} />
          <textarea placeholder="Objective" value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} style={{ ...inputStyle, gridColumn: '1 / -1', minHeight: 60, fontFamily: 'inherit' }} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <input type="checkbox" checked={form.application_signed} onChange={(e) => setForm({ ...form, application_signed: e.target.checked })} />
            Application signed
          </label>
          <button type="submit" className="btn btn-primary" style={{ gridColumn: '1 / -1' }}>Create</button>
        </form>
      )}

      {communities.length === 0 ? (
        <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>No ILC groups yet — create one above.</div>
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

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
