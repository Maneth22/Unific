import React from 'react'
import { Link } from 'react-router-dom'
import LandChangeSpotlight from '../components/public/LandChangeSpotlight'

const FEATURES = [
  {
    title: 'Accounts Room',
    body: 'A clear, auditable record of every account and every transaction — built so partners and donors can trust exactly where support goes.',
  },
  {
    title: 'Profiles Room',
    body: 'One consented, permissioned registry of every community and identity you work with — no message reaches anyone without passing through it first.',
  },
  {
    title: 'Meeting Room',
    body: 'Live translated conversations and video meetings that reach people in their own language, on WhatsApp or in a call — wherever they already are.',
  },
]

export default function LandingPage() {
  return (
    <div>
      <section className="public-hero">
        <h1>Accountable technology for community-led development</h1>
        <p>
          UNIFIC gives organisations and the communities they serve one shared, verifiable
          platform for accounts, identity, and communication — built with consent and an
          audit trail at every step.
        </p>
        <div className="public-hero-actions">
          <Link to="/login" className="btn btn-primary">Log in</Link>
          <Link to="/support/login" className="btn">Staff &amp; Partners — join as a supporter</Link>
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
              <h3>{f.title}</h3>
              <p>{f.body}</p>
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
