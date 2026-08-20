import React, { useEffect, useMemo, useState } from 'react'
import {
  getIdentityToolConfig, listGlobalToolSelections, listToolCatalog,
  setToolCatalogEntryEnabled, updateGlobalToolSelection, updateIdentityToolConfig,
} from '../../api/tools'
import { getTranslationLanguages } from '../../api/meetingRoom'
import { LANGUAGE_LABELS } from '../../components/video-call/callConstants'

// Every slot the Tools Registry covers — "global" slots (whatsapp_send,
// video_provider) are singleton platform infra with no per-identity
// override at all; everything else cascades through profiles.permission
// the same way reply role/tone/etc already does. "perLanguage" slots need
// one row per selectable language instead of one row total.
const SLOTS = [
  { key: 'whatsapp_send', label: 'WhatsApp Sender', global: true },
  { key: 'video_provider', label: 'Video Provider (LiveKit)', global: true },
  { key: 'reply_generator', label: 'WhatsApp Auto-Reply Generator', global: false },
  { key: 'comms_agent', label: 'Comms Agent', global: false },
  { key: 'meeting_translation', label: 'Meeting Live Translation', global: false },
  { key: 'meeting_stt', label: 'Meeting Speech-to-Text', global: false, perLanguage: true },
  { key: 'meeting_tts', label: 'Meeting Text-to-Speech (needs a voice id)', global: false, perLanguage: true },
]

const GLOBAL_LANGUAGE = '*'

export default function ToolsRegistryPanel() {
  const [catalog, setCatalog] = useState([])
  const [globalSelections, setGlobalSelections] = useState([])
  const [languages, setLanguages] = useState(['en'])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savedKey, setSavedKey] = useState('')

  const catalogBySlot = useMemo(() => {
    const grouped = {}
    for (const entry of catalog) (grouped[entry.slot] ||= []).push(entry)
    return grouped
  }, [catalog])

  const globalByKey = useMemo(() => {
    const map = {}
    for (const row of globalSelections) map[`${row.slot}:${row.language}`] = row
    return map
  }, [globalSelections])

  async function refresh() {
    setLoading(true)
    setError('')
    try {
      const [c, g, langs] = await Promise.all([
        listToolCatalog(), listGlobalToolSelections(), getTranslationLanguages(),
      ])
      setCatalog(c)
      setGlobalSelections(g)
      setLanguages(langs)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load the Tools Registry')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  function flashSaved(key) {
    setSavedKey(key)
    setTimeout(() => setSavedKey(''), 1500)
  }

  async function handleToggleEnabled(entry) {
    setError('')
    try {
      await setToolCatalogEntryEnabled(entry.slot, entry.tool_key, !entry.is_enabled)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update the catalog entry')
    }
  }

  async function handleSaveGlobal(slotKey, language, toolKey, voice) {
    setError('')
    try {
      await updateGlobalToolSelection(slotKey, { tool_key: toolKey, language, voice: voice || null })
      flashSaved(`global:${slotKey}:${language}`)
      await refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save the default')
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Every pluggable service UNIFIC can use — which speech-to-text/text-to-speech/translation
        backend a meeting uses, which model drafts a WhatsApp auto-reply, which WhatsApp/LiveKit
        provider the whole platform sends through. Staff set the system-wide default below; a
        client organization admin can override the five non-infra slots for their own
        organization (from their dashboard) — see docs/ARCHITECTURE.md's Tools Registry section.
      </p>

      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 12, padding: '8px 12px' }}>{error}</div>}
      {loading ? <div>Loading…</div> : (
        <>
          <GlobalDefaultsCard
            catalogBySlot={catalogBySlot} globalByKey={globalByKey} languages={languages}
            onSave={handleSaveGlobal} savedKey={savedKey}
          />
          <IdentityOverrideCard catalogBySlot={catalogBySlot} languages={languages} />
          <CatalogCard catalog={catalog} onToggle={handleToggleEnabled} />
        </>
      )}
    </div>
  )
}

function GlobalDefaultsCard({ catalogBySlot, globalByKey, languages, onSave, savedKey }) {
  return (
    <div className="card" style={{ padding: 16, marginBottom: 20 }}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Staff / System-wide defaults</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {SLOTS.flatMap((slot) => {
          const rowLanguages = slot.perLanguage ? languages : [GLOBAL_LANGUAGE]
          return rowLanguages.map((lang) => (
            <SlotRow
              key={`${slot.key}:${lang}`}
              slotKey={slot.key}
              label={slot.perLanguage ? `${slot.label} — ${LANGUAGE_LABELS[lang] || lang}` : slot.label}
              language={lang}
              options={catalogBySlot[slot.key] || []}
              current={globalByKey[`${slot.key}:${lang}`]}
              needsVoice={slot.key === 'meeting_tts'}
              saveLabel={savedKey === `global:${slot.key}:${lang}` ? '✓ saved' : 'Save'}
              onSave={(toolKey, voice) => onSave(slot.key, lang, toolKey, voice)}
            />
          ))
        })}
      </div>
    </div>
  )
}

function SlotRow({ label, options, current, needsVoice, onSave, saveLabel, allowClear }) {
  const [toolKey, setToolKey] = useState(current?.tool_key || '')
  const [voice, setVoice] = useState(current?.voice || '')

  useEffect(() => {
    setToolKey(current?.tool_key || '')
    setVoice(current?.voice || '')
  }, [current?.tool_key, current?.voice])

  const dirty = toolKey !== (current?.tool_key || '') || (needsVoice && voice !== (current?.voice || ''))
  // Global defaults are the root of the cascade — they can never be
  // "cleared" (there's nothing to inherit from). An identity override CAN
  // be cleared (empty selection = "inherit from parent/default again").
  const canSave = allowClear ? dirty : Boolean(toolKey) && dirty && (!needsVoice || voice)

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div style={{ minWidth: 260, fontSize: 13 }}>{label}</div>
      <select value={toolKey} onChange={(e) => setToolKey(e.target.value)} style={inputStyle}>
        <option value="">{allowClear ? '— inherit —' : '— choose —'}</option>
        {options.map((o) => (
          <option key={o.tool_key} value={o.tool_key} disabled={!o.is_enabled}>
            {o.display_name}{!o.is_enabled ? ' (disabled)' : ''}{o.package_version ? ` · v${o.package_version}` : ''}
          </option>
        ))}
      </select>
      {needsVoice && (
        <input
          placeholder="voice id (e.g. hi-IN-SwaraNeural)"
          value={voice}
          onChange={(e) => setVoice(e.target.value)}
          style={{ ...inputStyle, width: 220 }}
          disabled={allowClear && !toolKey}
        />
      )}
      <button className="btn btn-primary" disabled={!canSave} onClick={() => onSave(toolKey, voice)}>
        {saveLabel}
      </button>
    </div>
  )
}

function CatalogCard({ catalog, onToggle }) {
  return (
    <div className="card" style={{ padding: 16, marginBottom: 20 }}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Tool catalog</div>
      <p style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 10 }}>
        What's registered in code and available to select. Disabling a tool here stops it being
        offered for new selections going forward — it does not affect anyone already using it.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {catalog.map((entry) => (
          <div
            key={`${entry.slot}:${entry.tool_key}`}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '6px 10px', borderBottom: '1px solid var(--line)', fontSize: 13,
            }}
          >
            <div>
              <span className="badge badge-room" style={{ marginRight: 8 }}>{entry.slot}</span>
              <strong>{entry.display_name}</strong>
              <span style={{ color: 'var(--sub)', marginLeft: 8, fontSize: 12 }}>
                {entry.package_name ? `${entry.package_name}${entry.package_version ? ` v${entry.package_version}` : ' (not installed)'}` : 'built-in'}
              </span>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input type="checkbox" checked={entry.is_enabled} onChange={() => onToggle(entry)} />
              enabled
            </label>
          </div>
        ))}
      </div>
    </div>
  )
}

function IdentityOverrideCard({ catalogBySlot, languages }) {
  const [identityId, setIdentityId] = useState('')
  const [config, setConfig] = useState(null)
  const [error, setError] = useState('')
  const [savedKey, setSavedKey] = useState('')

  async function handleLoad(e) {
    e.preventDefault()
    setError('')
    try {
      setConfig(await getIdentityToolConfig(identityId))
    } catch (err) {
      setError('Identity not found')
      setConfig(null)
    }
  }

  async function handleSave(slotKey, language, toolKey, voice) {
    setError('')
    try {
      const updated = await updateIdentityToolConfig(identityId, {
        slot: slotKey, tool_key: toolKey || null, language, voice: voice || null,
      })
      setConfig(updated)
      setSavedKey(`${slotKey}:${language}`)
      setTimeout(() => setSavedKey(''), 1500)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save the override')
    }
  }

  const cascadingSlots = SLOTS.filter((s) => !s.global)

  return (
    <div className="card" style={{ padding: 16, marginBottom: 20 }}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Per-identity override</div>
      <p style={{ fontSize: 12, color: 'var(--sub)', marginBottom: 10 }}>
        Overrides here cascade to every descendant identity that hasn't set its own override —
        same inheritance as the Meeting Room's Config Board. Clear a field (leave it blank and
        save) to go back to inheriting from the parent/system default.
      </p>
      <form onSubmit={handleLoad} style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input placeholder="Identity ID" required value={identityId} onChange={(e) => setIdentityId(e.target.value)} style={{ flex: 1, ...inputStyle }} />
        <button type="submit" className="btn">Load</button>
      </form>
      {error && <div className="badge badge-alert" style={{ display: 'block', marginBottom: 10, padding: '6px 10px' }}>{error}</div>}
      {config && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {cascadingSlots.flatMap((slot) => {
            const rowLanguages = slot.perLanguage ? languages : [GLOBAL_LANGUAGE]
            return rowLanguages.map((lang) => {
              const effective = slot.perLanguage
                ? config[slot.key]?.[lang]
                : { tool_key: config[slot.key] }
              const own = slot.perLanguage
                ? config[`own_${slot.key}`]?.[lang]
                : config[`own_${slot.key}`] ? { tool_key: config[`own_${slot.key}`] } : null
              const effectiveToolKey = slot.perLanguage
                ? (effective?.provider || effective)
                : effective?.tool_key
              const effectiveVoice = slot.perLanguage ? effective?.voice : undefined
              return (
                <div key={`${slot.key}:${lang}`}>
                  <div style={{ fontSize: 11, color: 'var(--sub)', marginBottom: 2 }}>
                    effective: {effectiveToolKey || '—'}{own ? '' : ' (inherited)'}
                  </div>
                  <SlotRow
                    slotKey={slot.key}
                    label={slot.perLanguage ? `${slot.label} — ${LANGUAGE_LABELS[lang] || lang}` : slot.label}
                    language={lang}
                    options={catalogBySlot[slot.key] || []}
                    current={own ? { tool_key: own.provider || own, voice: own.voice } : { tool_key: '', voice: '' }}
                    needsVoice={slot.key === 'meeting_tts'}
                    allowClear
                    saveLabel={savedKey === `${slot.key}:${lang}` ? '✓ saved' : 'Save'}
                    onSave={(toolKey, voice) => handleSave(slot.key, lang, toolKey, voice)}
                  />
                </div>
              )
            })
          })}
        </div>
      )}
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
