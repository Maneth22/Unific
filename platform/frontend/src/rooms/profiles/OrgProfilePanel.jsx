import React, { useEffect, useState } from 'react'
import { getClientOrgProfile, getIlcGroupProfile, updateClientOrgProfile } from '../../api/profiles'

// Shows whichever profile the selected identity actually has — a client
// org (editable here by staff) or an ILC community group (read-only here;
// the client manages their own group's fields from their dashboard).
// Neither is shown for a plain group or a member identity.
export default function OrgProfilePanel({ identityId }) {
  const [kind, setKind] = useState(null) // 'client_org' | 'ilc_group' | 'none'
  const [profile, setProfile] = useState(null)
  const [form, setForm] = useState({ entity_type: '', role_description: '', abn_acnc_number: '' })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setMessage('')
    setError('')
    getClientOrgProfile(identityId)
      .then((p) => {
        setKind('client_org')
        setProfile(p)
        setForm({ entity_type: p.entity_type, role_description: p.role_description, abn_acnc_number: p.abn_acnc_number || '' })
      })
      .catch(() =>
        getIlcGroupProfile(identityId)
          .then((p) => {
            setKind('ilc_group')
            setProfile(p)
          })
          .catch(() => {
            setKind('none')
            setProfile(null)
          })
      )
  }, [identityId])

  async function handleSave(e) {
    e.preventDefault()
    setError('')
    try {
      const updated = await updateClientOrgProfile(identityId, { ...form, abn_acnc_number: form.abn_acnc_number || null })
      setProfile(updated)
      setMessage('Saved.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save')
    }
  }

  if (kind === null) return null

  if (kind === 'none') {
    return <div className="card" style={{ padding: 20, color: 'var(--sub)' }}>Not a client org or ILC group — no profile fields.</div>
  }

  if (kind === 'client_org') {
    return (
      <div className="card" style={{ padding: 18, maxWidth: 480 }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Client organization</div>
        <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 14 }}>Group ID: <code>{profile.group_code}</code></div>
        {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 10, padding: '8px 12px' }}>{message}</div>}
        {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '8px 12px' }}>{error}</div>}
        <form onSubmit={handleSave} style={{ display: 'grid', gap: 8 }}>
          <label style={labelStyle}>Entity type</label>
          <input value={form.entity_type} onChange={(e) => setForm({ ...form, entity_type: e.target.value })} style={inputStyle} />
          <label style={labelStyle}>Role</label>
          <input value={form.role_description} onChange={(e) => setForm({ ...form, role_description: e.target.value })} style={inputStyle} />
          <label style={labelStyle}>ABN / ACNC number</label>
          <input value={form.abn_acnc_number} onChange={(e) => setForm({ ...form, abn_acnc_number: e.target.value })} style={inputStyle} />
          <button type="submit" className="btn btn-primary">Save</button>
        </form>
      </div>
    )
  }

  // ILC group — read-only here, managed by the client themselves.
  return (
    <div className="card" style={{ padding: 18, maxWidth: 480 }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>ILC community group</div>
      <div style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 14 }}>Group ID: <code>{profile.group_code}</code></div>
      <Row label="Name (Hindi)">{profile.name_hindi || '—'}</Row>
      <Row label="Registration number">{profile.registration_number || '—'}</Row>
      <Row label="Date of registration">{profile.date_of_registration || '—'}</Row>
      <Row label="Application signed">{profile.application_signed ? 'Yes' : 'No'}</Row>
      <Row label="Registered office">{profile.registered_office || '—'}</Row>
      <Row label="Area of operation">{profile.area_of_operation || '—'}</Row>
      <Row label="Governing Act">{profile.governing_act || '—'}</Row>
      <Row label="Registering authority">{profile.registering_authority || '—'}</Row>
      <Row label="Cooperative type">{profile.cooperative_type || '—'}</Row>
      <Row label="Bank account">{profile.bank_account || '—'}</Row>
      <Row label="Objective">{profile.objective || '—'}</Row>
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 13 }}>
      <span style={{ color: 'var(--sub)', minWidth: 150, flexShrink: 0 }}>{label}</span>
      <span>{children}</span>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
const labelStyle = { fontSize: 12, fontWeight: 600, color: 'var(--sub)' }
