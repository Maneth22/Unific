import React, { useEffect, useState } from 'react'
import { getPermission, updatePermission } from '../../api/profiles'

const SCOPES = ['none', 'within_tree', 'any']

export default function PermissionsEditor({ identityId }) {
  const [perm, setPerm] = useState(null)
  const [form, setForm] = useState({})
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    setError('')
    setMessage('')
    getPermission(identityId).then(setPerm)
  }, [identityId])

  if (!perm) return <div>Loading…</div>

  async function handleSave(e) {
    e.preventDefault()
    setError('')
    setMessage('')
    const payload = {}
    for (const [key, value] of Object.entries(form)) {
      if (value !== undefined && value !== '') payload[key] = value
    }
    try {
      const updated = await updatePermission(identityId, payload)
      setPerm(updated)
      setForm({})
      setMessage('Saved — effective permissions recomputed down the subtree.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update permission')
    }
  }

  const field = (key) => form[key] !== undefined ? form[key] : ''

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 14, fontSize: 13 }}>
        "Own" settings override inheritance; leaving a field blank inherits the parent's effective
        value. Narrowing is self-enforcing — a child can never end up wider than its parent, even
        if you try.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
      {message && <div className="badge badge-agent" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{message}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>EFFECTIVE (read-only)</div>
          <EffectiveRow label="Registered" value={String(perm.effective_registered)} />
          <EffectiveRow label="Connected" value={String(perm.effective_connected)} />
          <EffectiveRow label="Auto-respond" value={String(perm.effective_auto_respond)} />
          <EffectiveRow label="Send-on" value={String(perm.effective_send_on)} />
          <EffectiveRow label="Can message" value={perm.effective_can_message_scope} />
          <EffectiveRow label="Can receive" value={perm.effective_can_receive_scope} />
          <EffectiveRow label="Credit cap" value={perm.effective_credit_cap ?? 'unlimited'} />
          <EffectiveRow label="Role" value={perm.effective_reply_role} />
          <EffectiveRow label="Tone" value={perm.effective_reply_tone} />
          <EffectiveRow label="Complexity" value={perm.effective_reply_complexity} />
          <EffectiveRow label="Character" value={perm.effective_reply_character} />
          <EffectiveRow label="Language" value={perm.effective_reply_language} />
          <EffectiveRow label="Consent required" value={String(perm.consent_required)} />
        </div>

        <form onSubmit={handleSave}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>OWN OVERRIDE</div>
          <BoolField label="Registered" name="own_registered" value={field('own_registered')} onChange={setForm} form={form} />
          <BoolField label="Connected" name="own_connected" value={field('own_connected')} onChange={setForm} form={form} />
          <BoolField label="Auto-respond" name="own_auto_respond" value={field('own_auto_respond')} onChange={setForm} form={form} />
          <BoolField label="Send-on" name="own_send_on" value={field('own_send_on')} onChange={setForm} form={form} />
          <ScopeField label="Can message" name="own_can_message_scope" form={form} setForm={setForm} />
          <ScopeField label="Can receive" name="own_can_receive_scope" form={form} setForm={setForm} />
          <TextField label="Credit cap" name="own_credit_cap" form={form} setForm={setForm} type="number" />
          <TextField label="Role" name="own_reply_role" form={form} setForm={setForm} />
          <TextField label="Tone" name="own_reply_tone" form={form} setForm={setForm} />
          <TextField label="Complexity" name="own_reply_complexity" form={form} setForm={setForm} />
          <TextField label="Character" name="own_reply_character" form={form} setForm={setForm} />
          <TextField label="Language" name="own_reply_language" form={form} setForm={setForm} />
          <button type="submit" className="btn btn-primary" style={{ marginTop: 10 }}>Save overrides</button>
        </form>
      </div>
    </div>
  )
}

function EffectiveRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--line)' }}>
      <span style={{ color: 'var(--sub)' }}>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function BoolField({ label, name, form, onChange }) {
  const value = form[name]
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
      <span style={{ fontSize: 12 }}>{label}</span>
      <select
        value={value === undefined ? '' : String(value)}
        onChange={(e) => onChange({ ...form, [name]: e.target.value === '' ? undefined : e.target.value === 'true' })}
        style={{ ...smallInput, width: 110 }}
      >
        <option value="">inherit</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    </div>
  )
}

function ScopeField({ label, name, form, setForm }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
      <span style={{ fontSize: 12 }}>{label}</span>
      <select
        value={form[name] ?? ''}
        onChange={(e) => setForm({ ...form, [name]: e.target.value || undefined })}
        style={{ ...smallInput, width: 110 }}
      >
        <option value="">inherit</option>
        {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </div>
  )
}

function TextField({ label, name, form, setForm, type = 'text' }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
      <span style={{ fontSize: 12 }}>{label}</span>
      <input
        type={type}
        value={form[name] ?? ''}
        onChange={(e) => setForm({ ...form, [name]: e.target.value || undefined })}
        style={{ ...smallInput, width: 110 }}
      />
    </div>
  )
}

const smallInput = { padding: 5, border: '1px solid var(--line)', borderRadius: 6, fontSize: 12 }
