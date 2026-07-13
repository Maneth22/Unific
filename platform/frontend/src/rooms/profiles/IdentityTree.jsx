import React, { useEffect, useState } from 'react'
import { createIdentity, listIdentities } from '../../api/profiles'

function buildTree(flat) {
  const byId = Object.fromEntries(flat.map((n) => [n.id, { ...n, children: [] }]))
  const roots = []
  for (const node of Object.values(byId)) {
    if (node.parent_id && byId[node.parent_id]) {
      byId[node.parent_id].children.push(node)
    } else {
      roots.push(node)
    }
  }
  return roots
}

function TreeNode({ node, selectedId, onSelect, depth }) {
  return (
    <div>
      <div
        onClick={() => onSelect(node.id)}
        style={{
          padding: '6px 8px',
          marginLeft: depth * 16,
          borderRadius: 6,
          cursor: 'pointer',
          fontSize: 13,
          background: selectedId === node.id ? 'var(--slate-bg)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span className={`badge ${node.id_type === 'group' ? 'badge-id' : 'badge-agent'}`}>{node.id_type}</span>
        {node.name}
      </div>
      {node.children.map((c) => (
        <TreeNode key={c.id} node={c} selectedId={selectedId} onSelect={onSelect} depth={depth + 1} />
      ))}
    </div>
  )
}

export default function IdentityTree({ selectedId, onSelect }) {
  const [identities, setIdentities] = useState([])
  const [form, setForm] = useState({ name: '', id_type: 'group', parent_id: '' })
  const [error, setError] = useState('')

  async function refresh() {
    setIdentities(await listIdentities())
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      const created = await createIdentity({ ...form, parent_id: form.parent_id || null })
      setForm({ name: '', id_type: 'group', parent_id: '' })
      await refresh()
      onSelect(created.id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create identity')
    }
  }

  const tree = buildTree(identities)

  return (
    <div className="card" style={{ padding: 14, width: 320, flexShrink: 0 }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>Identity tree</div>

      <div style={{ maxHeight: 360, overflowY: 'auto', marginBottom: 14 }}>
        {tree.map((n) => (
          <TreeNode key={n.id} node={n} selectedId={selectedId} onSelect={onSelect} depth={0} />
        ))}
        {tree.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No identities yet.</div>}
      </div>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}

      <form onSubmit={handleCreate} style={{ display: 'grid', gap: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--sub)' }}>Add identity</div>
        <input placeholder="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={inputStyle} />
        <select value={form.id_type} onChange={(e) => setForm({ ...form, id_type: e.target.value })} style={inputStyle}>
          <option value="group">Group ID</option>
          <option value="member">Member ID</option>
        </select>
        <select value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })} style={inputStyle}>
          <option value="">— no parent (new root) —</option>
          {identities.filter((i) => i.id_type === 'group').map((i) => (
            <option key={i.id} value={i.id}>{i.name}</option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary">Add</button>
      </form>
    </div>
  )
}

const inputStyle = { padding: 7, border: '1px solid var(--line)', borderRadius: 8, fontSize: 13 }
