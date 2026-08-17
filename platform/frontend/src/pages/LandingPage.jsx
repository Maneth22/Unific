import React from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, MessageSquare, Users, Wallet } from 'lucide-react'
import LandChangeSpotlight from '../components/public/LandChangeSpotlight'

const FEATURES = [
  {
    icon: Wallet,
    title: 'Accounts Room',
    to: '/support/login',
    body: 'A clear, auditable record of every account and every transaction — built so partners and donors can trust exactly where support goes.',
  },
  {
    icon: Users,
    title: 'Profiles Room',
    to: '/support/login',
    body: 'One consented, permissioned registry of every community and identity you work with — no message reaches anyone without passing through it first.',
  },
  {
    icon: MessageSquare,
    title: 'Meeting Room',
    to: '/support/login',
    body: 'Live translated conversations and video meetings that reach people in their own language, on WhatsApp or in a call — wherever they already are.',
  },
]

// Decorative, deliberately abstract (no stock photography, no fabricated
// people/scenes) — a handful of soft geometric shapes in the platform's own
// blue palette, standing in for "connected accounts/identity/communication".
function HeroGraphic() {
  return (
    <svg viewBox="0 0 420 360" fill="none" xmlns="http://www.w3.org/2000/svg" role="presentation" aria-hidden="true">
      <circle cx="210" cy="180" r="170" fill="var(--blue-tint)" />
      <rect x="90" y="120" width="150" height="150" rx="24" fill="var(--surface)" stroke="var(--line)" />
      <rect x="180" y="70" width="120" height="120" rx="20" fill="var(--token)" opacity="0.9" />
      <circle cx="300" cy="250" r="46" fill="var(--surface)" stroke="var(--token)" strokeWidth="2" />
      <path d="M283 250 L295 262 L318 236" stroke="var(--token)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="120" cy="255" r="30" fill="var(--green-bg)" stroke="var(--green)" strokeWidth="2" />
      <rect x="107" y="248" width="26" height="4" rx="2" fill="var(--green)" />
      <rect x="107" y="256" width="18" height="4" rx="2" fill="var(--green)" />
      <rect x="205" y="100" width="70" height="10" rx="5" fill="var(--surface)" opacity="0.85" />
      <rect x="205" y="118" width="46" height="10" rx="5" fill="var(--surface)" opacity="0.6" />
    </svg>
  )
}

export default function LandingPage() {
  return (
    <div>
      <section className="public-hero-split">
        <div className="public-hero-copy">
          <h1>Accountable technology for community-led development</h1>
          <p>
            UNIFIC gives organisations and the communities they serve one shared, verifiable
            platform for accounts, identity, and communication — built with consent and an
            audit trail at every step.
          </p>
          <div className="public-hero-actions" style={{ justifyContent: 'flex-start' }}>
            <Link to="/login" className="btn btn-primary">Log in</Link>
            <Link to="/support/login" className="btn">Staff &amp; Partners — join as a supporter</Link>
          </div>
        </div>
        <div className="public-hero-graphic">
          <HeroGraphic />
        </div>
      </section>

      <section className="public-section public-section-alt">
        <LandChangeSpotlight variant="compact" />
      </section>

      <section className="public-section">
        <h2>What UNIFIC does</h2>
        <p className="public-section-lead">
          Three rooms, one registry — everything an organisation needs to run accountable,
          community-facing operations.
        </p>
        <div className="public-feature-grid">
          {FEATURES.map((f) => (
            <div key={f.title} className="card public-feature-card">
              <span className="public-feature-icon">
                <f.icon size={18} />
              </span>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
              <Link to={f.to} className="public-feature-link">
                Explore <ArrowRight size={13} />
              </Link>
            </div>
          ))}
        </div>
      </section>

      <section className="public-cta-band">
        <h2>Ready to sign in?</h2>
        <div className="public-hero-actions">
          <Link to="/login" className="btn btn-primary">Log in</Link>
          <Link to="/support/login" className="btn">Staff &amp; Partners</Link>
        </div>
      </section>
    </div>
  )
}
