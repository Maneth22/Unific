import React from 'react'
import { Link } from 'react-router-dom'

// Static page only — no submission form, no backend call. Replace the
// placeholder email below with a real inbox before shipping.
export default function ContactPage() {
  return (
    <div>
      <section className="public-hero" style={{ paddingBottom: 32 }}>
        <h1>Contact us</h1>
        <p>We'd like to hear from you — reach out and we'll get back to you.</p>
      </section>

      <section className="public-section" style={{ maxWidth: 560 }}>
        <div className="card" style={{ padding: 28 }}>
          <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>General inquiries</h3>
          <p style={{ margin: '0 0 20px', color: 'var(--sub)', fontSize: 13 }}>
            <a href="mailto:hello@unific.example">hello@unific.example</a>
          </p>

          <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>Already work with us?</h3>
          <p style={{ margin: 0, color: 'var(--sub)', fontSize: 13 }}>
            Staff and partner organisations can{' '}
            <Link to="/support/login">sign in here</Link>, and clients can{' '}
            <Link to="/login">log in here</Link>.
          </p>
        </div>
      </section>
    </div>
  )
}
