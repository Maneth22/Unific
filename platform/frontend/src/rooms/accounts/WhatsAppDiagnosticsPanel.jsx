import React, { useEffect, useState } from 'react'
import { getWhatsAppWebhookLog, getWhatsAppWebhookStatus, whatsAppTestSend } from '../../api/accounts'

const EMPTY_FORM = { to_number: '', message_type: 'text', text: '', template_name: '', body_params: '', language: 'en_US' }

export default function WhatsAppDiagnosticsPanel() {
  const [status, setStatus] = useState(null)
  const [statusError, setStatusError] = useState('')
  const [log, setLog] = useState([])
  const [expandedId, setExpandedId] = useState('')
  const [form, setForm] = useState(EMPTY_FORM)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)
  const [formError, setFormError] = useState('')

  async function refreshStatus() {
    try {
      setStatus(await getWhatsAppWebhookStatus())
      setStatusError('')
    } catch (err) {
      setStatusError(err.response?.data?.detail || 'Could not load webhook status')
    }
  }

  async function refreshLog() {
    setLog(await getWhatsAppWebhookLog(50))
  }

  useEffect(() => {
    refreshStatus()
    refreshLog()
  }, [])

  async function handleSend(e) {
    e.preventDefault()
    setFormError('')
    setResult(null)
    if (form.message_type === 'text' && !form.text.trim()) {
      setFormError('Enter a message body')
      return
    }
    if (form.message_type === 'template' && !form.template_name.trim()) {
      setFormError('Enter a template name')
      return
    }
    setSending(true)
    try {
      const payload = {
        to_number: form.to_number,
        message_type: form.message_type,
        text: form.message_type === 'text' ? form.text : undefined,
        template_name: form.message_type === 'template' ? form.template_name : undefined,
        template_params:
          form.message_type === 'template'
            ? {
                language: form.language || 'en_US',
                body_params: form.body_params
                  .split(',')
                  .map((p) => p.trim())
                  .filter(Boolean),
              }
            : undefined,
      }
      const res = await whatsAppTestSend(payload)
      setResult(res)
      await refreshLog()
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Send failed')
    } finally {
      setSending(false)
    }
  }

  return (
    <div>
      <p style={{ color: 'var(--sub)', marginBottom: 16 }}>
        Validates the WhatsApp Cloud API integration itself — sends to any number (not required to
        be a linked identity) and shows exactly what Meta sent/received. Separate from the Meeting
        Room's per-identity comms pipeline; each send here is UNIFIC's own operational testing cost.
      </p>

      {/* Webhook status */}
      <div className="card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: status ? 10 : 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Webhook status</div>
          <button className="btn" onClick={refreshStatus} style={{ fontSize: 11, padding: '4px 10px' }}>Refresh</button>
        </div>
        {statusError && <div className="badge badge-alert" style={{ display: 'block', padding: '8px 12px' }}>{statusError}</div>}
        {status && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span className={`badge ${status.matches ? 'badge-agent' : 'badge-alert'}`}>
              {status.matches ? 'callback URL matches' : 'callback URL mismatch or not configured'}
            </span>
            <span style={{ fontSize: 12, color: 'var(--sub)' }}>
              Meta has: <code>{status.callback_url || '—'}</code>
            </span>
            <span style={{ fontSize: 12, color: 'var(--sub)' }}>
              Expected: <code>{status.expected_callback_url}</code>
            </span>
            {status.fields.length > 0 && (
              <span style={{ fontSize: 12, color: 'var(--sub)' }}>Fields: {status.fields.join(', ')}</span>
            )}
            {status.error && <span style={{ fontSize: 12, color: 'var(--red)' }}>{status.error}</span>}
          </div>
        )}
      </div>

      {/* Send test message */}
      <form onSubmit={handleSend} className="card" style={{ padding: 16, marginBottom: 20, display: 'grid', gap: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Send a test message</div>
        {formError && <div className="badge badge-alert" style={{ display: 'block', padding: '8px 12px' }}>{formError}</div>}

        <input
          required
          placeholder="Phone number, e.g. +15551234567"
          value={form.to_number}
          onChange={(e) => setForm({ ...form, to_number: e.target.value })}
          style={inputStyle}
        />

        <div style={{ display: 'flex', gap: 6 }}>
          {['text', 'template'].map((t) => (
            <button
              key={t}
              type="button"
              className={form.message_type === t ? 'btn btn-primary' : 'btn'}
              onClick={() => setForm({ ...form, message_type: t })}
            >
              {t === 'text' ? 'Text' : 'Template'}
            </button>
          ))}
        </div>

        {form.message_type === 'text' ? (
          <textarea
            required
            placeholder="Message body"
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
            style={{ ...inputStyle, minHeight: 70, fontFamily: 'inherit' }}
          />
        ) : (
          <>
            <input
              required
              placeholder="Template name"
              value={form.template_name}
              onChange={(e) => setForm({ ...form, template_name: e.target.value })}
              style={inputStyle}
            />
            <input
              placeholder="Body params, comma-separated (matches {{1}}, {{2}}, ...)"
              value={form.body_params}
              onChange={(e) => setForm({ ...form, body_params: e.target.value })}
              style={inputStyle}
            />
            <input
              placeholder="Language code (default en_US)"
              value={form.language}
              onChange={(e) => setForm({ ...form, language: e.target.value })}
              style={inputStyle}
            />
          </>
        )}

        <button type="submit" className="btn btn-primary" disabled={sending}>
          {sending ? 'Sending…' : 'Send'}
        </button>

        {result && (
          <div
            className="card"
            style={{
              padding: 12,
              background: result.success ? 'var(--green-bg)' : 'var(--red-bg)',
              color: result.success ? 'var(--green)' : 'var(--red)',
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{result.success ? 'Sent' : 'Failed'}</div>
            <div style={{ fontSize: 12 }}>
              {result.success
                ? `Message id: ${result.provider_message_id}`
                : result.error}
            </div>
          </div>
        )}
      </form>

      {/* Raw payload log */}
      <div className="card" style={{ padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Recent webhook traffic</div>
          <button className="btn" onClick={refreshLog} style={{ fontSize: 11, padding: '4px 10px' }}>Refresh</button>
        </div>
        <div style={{ maxHeight: 420, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {log.map((entry) => (
            <div key={entry.id} className="card card-clickable" style={{ padding: 10 }} onClick={() => setExpandedId(expandedId === entry.id ? '' : entry.id)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <div>
                  <span className={`badge ${entry.direction === 'inbound' ? 'badge-id' : 'badge-account'}`} style={{ marginRight: 6 }}>
                    {entry.direction}
                  </span>
                  <span
                    className={`badge ${entry.status.startsWith('error') || entry.status === 'invalid_object' ? 'badge-alert' : 'badge-agent'}`}
                    style={{ marginRight: 6 }}
                  >
                    {entry.status}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--sub)' }}>{entry.provider}</span>
                </div>
                <span style={{ fontSize: 11, color: 'var(--sub)', whiteSpace: 'nowrap' }}>
                  {new Date(entry.created_at).toLocaleString()}
                </span>
              </div>
              {expandedId === entry.id && (
                <pre
                  style={{
                    marginTop: 8, padding: 10, background: 'var(--neutral-bg)', borderRadius: 6,
                    fontSize: 11, overflowX: 'auto', maxHeight: 300,
                  }}
                >
                  {JSON.stringify(entry.raw_payload, null, 2)}
                </pre>
              )}
            </div>
          ))}
          {log.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No webhook traffic logged yet.</div>}
        </div>
      </div>
    </div>
  )
}

const inputStyle = { padding: 8, border: '1px solid var(--line)', borderRadius: 8 }
