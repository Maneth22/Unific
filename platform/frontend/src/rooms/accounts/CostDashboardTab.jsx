import React, { useEffect, useMemo, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts'
import { getCostTimeseries, getFinancialTimeseries, getUsageByClientNeed } from '../../api/accounts'
import { listConcerns, listTasksDashboard } from '../../api/tasking'

// Validated categorical palette (reference instance, `dataviz` skill —
// fixed hue order, never cycled/reassigned; passes the CVD/normal-vision
// gates as a set). Scoped as CSS vars so light/dark swap in one place.
const SERIES_VARS = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6', '--series-7', '--series-8']

function pivotTimeseries(rows) {
  const byPeriod = new Map()
  const groups = new Set()
  for (const row of rows) {
    const label = new Date(row.period).toLocaleDateString()
    groups.add(row.group_value)
    if (!byPeriod.has(label)) byPeriod.set(label, { period: label })
    byPeriod.get(label)[row.group_value] = Number(row.total_cost)
  }
  return { data: Array.from(byPeriod.values()), groups: Array.from(groups).slice(0, 8) } // cap at 8 categorical slots
}

const STATUS_BADGE = {
  open: 'badge-pending', in_progress: 'badge-agent', blocked: 'badge-alert', completed: 'badge-room', cancelled: 'badge-alert',
}

export default function CostDashboardTab() {
  const [bucket, setBucket] = useState('day')
  const [groupBy, setGroupBy] = useState('model')
  const [llmRows, setLlmRows] = useState([])
  const [financialRows, setFinancialRows] = useState([])
  const [byClientNeed, setByClientNeed] = useState([])
  const [showDrilldown, setShowDrilldown] = useState(false)
  const [tasks, setTasks] = useState([])
  const [concerns, setConcerns] = useState([])

  useEffect(() => {
    getCostTimeseries(bucket, groupBy).then(setLlmRows)
  }, [bucket, groupBy])

  useEffect(() => {
    getFinancialTimeseries(bucket).then(setFinancialRows)
  }, [bucket])

  useEffect(() => {
    getUsageByClientNeed().then(setByClientNeed)
    listTasksDashboard().then(setTasks)
    listConcerns().then(setConcerns)
  }, [])

  const llm = useMemo(() => pivotTimeseries(llmRows), [llmRows])
  const financial = useMemo(() => pivotTimeseries(financialRows.map((r) => ({ ...r, group_value: r.category, total_cost: r.total_amount }))), [financialRows])

  // Per-client-need drill-down needs its own pivot: rows are {identity_name, action, total_cost}.
  const clientNeed = useMemo(() => {
    const byClient = new Map()
    const actions = new Set()
    for (const row of byClientNeed) {
      const name = row.identity_name || '(unknown)'
      actions.add(row.action)
      if (!byClient.has(name)) byClient.set(name, { client: name })
      byClient.get(name)[row.action] = Number(row.total_cost)
    }
    return { data: Array.from(byClient.values()), actions: Array.from(actions).slice(0, 8) }
  }, [byClientNeed])

  return (
    <div className="viz-root">
      <style>{`
        .viz-root {
          --series-1: #2a78d6; --series-2: #008300; --series-3: #e87ba4; --series-4: #eda100;
          --series-5: #1baf7a; --series-6: #eb6834; --series-7: #4a3aa7; --series-8: #e34948;
          --chart-ink: var(--sub); --chart-grid: var(--line);
        }
        @media (prefers-color-scheme: dark) {
          .viz-root { --series-1: #3987e5; --series-3: #d55181; --series-4: #c98500; --series-6: #d95926; --series-8: #e66767; }
        }
      `}</style>

      <div style={{ display: 'flex', gap: 20, marginBottom: 20 }}>
        <StatTile label="Open tasks" value={tasks.filter((t) => t.status !== 'completed' && t.status !== 'cancelled').length} />
        <StatTile label="Open concerns" value={concerns.length} tone={concerns.length > 0 ? 'alert' : undefined} />
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'center' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--sub)' }}>LLM cost over time, by</span>
        <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)} style={selectStyle}>
          <option value="model">model</option>
          <option value="provider">provider</option>
          <option value="room">room</option>
          <option value="action">need (action)</option>
        </select>
        <select value={bucket} onChange={(e) => setBucket(e.target.value)} style={selectStyle}>
          <option value="day">daily</option>
          <option value="week">weekly</option>
        </select>
        <button className="btn" style={{ marginLeft: 'auto', fontSize: 12 }} onClick={() => setShowDrilldown(!showDrilldown)}>
          {showDrilldown ? 'Hide' : 'Show'} per-client breakdown
        </button>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 20 }}>
        {llm.data.length === 0 ? (
          <EmptyChart label="No LLM usage recorded yet." />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={llm.data} margin={{ left: 4, right: 12 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11, fill: 'var(--chart-ink)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--chart-ink)' }} width={50} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} formatter={(v) => `$${Number(v).toFixed(4)}`} />
              {llm.groups.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {llm.groups.map((g, i) => (
                <Line key={g} type="monotone" dataKey={g} stroke={`var(${SERIES_VARS[i]})`} strokeWidth={2} dot={{ r: 3 }} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {showDrilldown && (
        <div className="card" style={{ padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>LLM cost per client, by need</div>
          {clientNeed.data.length === 0 ? (
            <EmptyChart label="No client usage recorded yet." />
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(200, clientNeed.data.length * 40)}>
              <BarChart data={clientNeed.data} layout="vertical" margin={{ left: 12, right: 12 }}>
                <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--chart-ink)' }} />
                <YAxis type="category" dataKey="client" tick={{ fontSize: 11, fill: 'var(--chart-ink)' }} width={140} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} formatter={(v) => `$${Number(v).toFixed(4)}`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {clientNeed.actions.map((a, i) => (
                  <Bar key={a} dataKey={a} stackId="a" fill={`var(${SERIES_VARS[i]})`} radius={[0, 4, 4, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      )}

      <div className="card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>Other service costs over time, by category</div>
        {financial.data.length === 0 ? (
          <EmptyChart label="No manual expense records yet." />
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={financial.data} margin={{ left: 4, right: 12 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11, fill: 'var(--chart-ink)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--chart-ink)' }} width={50} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} formatter={(v) => `$${Number(v).toFixed(2)}`} />
              {financial.groups.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {financial.groups.map((g, i) => (
                <Line key={g} type="monotone" dataKey={g} stroke={`var(${SERIES_VARS[i]})`} strokeWidth={2} dot={{ r: 3 }} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="card" style={{ padding: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>Pending tasks — latest update &amp; concerns</div>
        {tasks.length === 0 && <div style={{ color: 'var(--sub)', fontSize: 13 }}>No tasks assigned yet.</div>}
        {tasks.map((t) => (
          <div key={t.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}>
            <span className={`badge ${STATUS_BADGE[t.status] || 'badge-room'}`}>{t.status}</span>{' '}
            <strong>{t.title}</strong>
            {t.latest_update && (
              <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 4 }}>
                {t.latest_update.is_concern && <span className="badge badge-alert" style={{ marginRight: 6 }}>concern</span>}
                {t.latest_update.note} — {new Date(t.latest_update.created_at).toLocaleString()}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function StatTile({ label, value, tone }) {
  return (
    <div className="card" style={{ padding: '14px 20px', minWidth: 140 }}>
      <div style={{ fontSize: 11, color: 'var(--sub)', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: tone === 'alert' && value > 0 ? 'var(--red)' : 'var(--ink)' }}>{value}</div>
    </div>
  )
}

function EmptyChart({ label }) {
  return <div style={{ padding: 30, textAlign: 'center', color: 'var(--sub)', fontSize: 13 }}>{label}</div>
}

const selectStyle = { padding: 6, border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }
