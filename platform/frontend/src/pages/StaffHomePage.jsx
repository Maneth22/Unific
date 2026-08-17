import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import {
  CalendarClock,
  Inbox,
  PlusCircle,
  UserPlus,
  Users,
  Video,
  Wallet,
  WalletCards,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { listIdentities, listRegistrationRequests } from '../api/profiles'
import { listRegistry } from '../api/accounts'
import { listMeetings } from '../api/meetingRoom'
import Card from '../components/ui/Card.jsx'
import StatCard from '../components/dashboard/StatCard.jsx'
import { SkeletonBlock, SkeletonLine } from '../components/ui/Skeleton.jsx'
import { relativeTime } from '../utils/time.js'

const DONUT_COLORS = ['var(--series-1)', 'var(--series-6)']
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000

function countRecent(items, field = 'created_at') {
  const cutoff = Date.now() - THIRTY_DAYS_MS
  return items.filter((it) => it[field] && new Date(it[field]).getTime() >= cutoff).length
}

function trendLabel(n) {
  return n > 0 ? `+${n} in last 30 days` : undefined
}

const QUICK_ACTIONS = [
  { key: 'accounts', to: '/accounts', label: 'Accounts Room', icon: WalletCards },
  { key: 'profiles', to: '/profiles', label: 'Add a new identity', icon: PlusCircle },
  { key: 'meetings', to: '/meeting-room', label: 'Schedule a meeting', icon: Video },
  { key: 'requests', to: '/registration-requests', label: 'Review client requests', icon: Inbox },
]

export default function StaffHomePage() {
  const { staff } = useAuth()
  const [data, setData] = useState(null) // { identities, registry, meetings, requests }
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([listIdentities(), listRegistry(), listMeetings(), listRegistrationRequests('pending')])
      .then(([identities, registry, meetings, requests]) => {
        if (!cancelled) setData({ identities, registry, meetings, requests })
      })
      .catch(() => !cancelled && setError('Some dashboard data failed to load — showing what is available.'))
    return () => {
      cancelled = true
    }
  }, [])

  const activity = useMemo(() => {
    if (!data) return []
    const items = [
      ...data.identities.map((i) => ({
        ts: i.created_at,
        icon: UserPlus,
        title: `New ${i.id_type === 'group' ? 'group' : 'member'} identity created`,
        desc: i.name,
        key: `identity-${i.id}`,
      })),
      ...data.registry.map((r) => ({
        ts: r.created_at,
        icon: Wallet,
        title: 'Registry account added',
        desc: r.name,
        key: `registry-${r.id}`,
      })),
      ...data.meetings.map((m) => ({
        ts: m.scheduled_at,
        icon: CalendarClock,
        title: 'Meeting scheduled',
        desc: m.notes || m.room_name,
        key: `meeting-${m.id}`,
      })),
      ...data.requests.map((r) => ({
        ts: r.created_at,
        icon: Inbox,
        title: 'New client request',
        desc: `${r.org_name} — ${r.contact_name}`,
        key: `request-${r.id}`,
      })),
    ]
    return items
      .filter((it) => it.ts)
      .sort((a, b) => new Date(b.ts) - new Date(a.ts))
      .slice(0, 6)
  }, [data])

  const donutData = useMemo(() => {
    if (!data) return []
    const groups = data.identities.filter((i) => i.id_type === 'group').length
    const members = data.identities.filter((i) => i.id_type === 'member').length
    return [
      { name: 'Groups', value: groups },
      { name: 'Members', value: members },
    ].filter((d) => d.value > 0)
  }, [data])

  const totalIdentities = data?.identities.length ?? 0

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>Welcome back, {staff?.full_name?.split(' ')[0]} 👋</h1>
          <p style={{ color: 'var(--sub)', margin: 0 }}>Here's what's happening across your rooms.</p>
        </div>
        <span style={{ fontSize: 12, color: 'var(--sub)', fontWeight: 600 }}>
          {new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
        </span>
      </div>

      {error && (
        <div className="card" style={{ padding: 12, marginBottom: 16, background: 'var(--amber-bg)', color: 'var(--amber)' }}>
          {error}
        </div>
      )}

      {!data ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14, marginBottom: 24 }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonBlock key={i} height={96} />
          ))}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14, marginBottom: 24 }}>
          <StatCard label="Total Identities" value={totalIdentities} trend={trendLabel(countRecent(data.identities))} icon={Users} />
          <StatCard label="Registry Accounts" value={data.registry.length} trend={trendLabel(countRecent(data.registry))} icon={WalletCards} />
          <StatCard label="Meetings" value={data.meetings.length} icon={Video} />
          <StatCard
            label="Pending Requests"
            value={data.requests.length}
            trend={trendLabel(countRecent(data.requests))}
            icon={Inbox}
          />
        </div>
      )}

      <div className="dashboard-grid">
        <Card>
          <h2 style={{ fontSize: 15, margin: '0 0 8px' }}>Recent Activity</h2>
          {!data ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonLine key={i} height={36} />
              ))}
            </div>
          ) : activity.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon">
                <Inbox size={20} />
              </span>
              <h3>No activity yet</h3>
              <p>New identities, accounts, meetings, and client requests will show up here.</p>
            </div>
          ) : (
            <div>
              {activity.map((item) => (
                <div className="activity-item" key={item.key}>
                  <span className="activity-icon">
                    <item.icon size={15} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div className="activity-title">{item.title}</div>
                    <div className="activity-desc">{item.desc}</div>
                  </div>
                  <span className="activity-time">{relativeTime(item.ts)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card>
            <h2 style={{ fontSize: 15, margin: '0 0 8px' }}>Identities by Type</h2>
            {!data ? (
              <SkeletonBlock height={180} />
            ) : donutData.length === 0 ? (
              <p style={{ color: 'var(--sub)', fontSize: 13 }}>No identities yet.</p>
            ) : (
              <div style={{ position: 'relative', height: 180 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={donutData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={78} paddingAngle={2}>
                      {donutData.map((_, i) => (
                        <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} stroke="var(--surface)" />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    pointerEvents: 'none',
                  }}
                >
                  <span style={{ fontSize: 22, fontWeight: 700, color: 'var(--navy)' }}>{totalIdentities}</span>
                  <span style={{ fontSize: 11, color: 'var(--sub)' }}>Total</span>
                </div>
              </div>
            )}
            {data && donutData.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
                {donutData.map((d, i) => (
                  <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 999, background: DONUT_COLORS[i % DONUT_COLORS.length] }} />
                    <span style={{ color: 'var(--sub)' }}>{d.name}</span>
                    <span style={{ marginLeft: 'auto', fontWeight: 700, color: 'var(--ink)' }}>{d.value}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <h2 style={{ fontSize: 15, margin: '0 0 10px' }}>Quick Actions</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {QUICK_ACTIONS.map((action) => (
                <Link key={action.key} to={action.to} className="quick-action-btn">
                  <action.icon size={16} />
                  {action.label}
                </Link>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
