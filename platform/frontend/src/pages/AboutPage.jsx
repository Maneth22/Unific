import React from 'react'
import LandChangeSpotlight from '../components/public/LandChangeSpotlight'

export default function AboutPage() {
  return (
    <div>
      <section className="public-hero" style={{ paddingBottom: 32 }}>
        <h1>About UNIFIC</h1>
        <p>
          UNIFIC is a platform for organisations that work directly with communities — one
          shared system for financial accounts, consented identity records, and translated,
          real-time communication, so every interaction stays accountable and verifiable.
        </p>
      </section>

      <section className="public-section">
        <h2>Our mission</h2>
        <p className="public-section-lead">
          We believe accountable development starts with a clear record: who was contacted,
          what was agreed, and where support went. UNIFIC exists to make that record easy to
          keep — for staff running the day-to-day work, and for the communities and partners
          who need to trust it.
        </p>
      </section>

      <section className="public-section public-section-alt">
        <LandChangeSpotlight variant="full" />
      </section>
    </div>
  )
}
