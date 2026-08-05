import React from 'react'

// Shared "who we work with" content — used on both the landing page
// (compact) and the About page (full), so the paraphrased copy about our
// partner organisation, LandChange, lives in exactly one place. Paraphrased
// in our own words from landchangefoundation.org — not a verbatim quote.
export default function LandChangeSpotlight({ variant = 'compact' }) {
  if (variant === 'full') {
    return (
      <div id="landchange">
        <h2>Who we work with</h2>
        <p className="public-section-lead">
          UNIFIC is built with and for LandChange, an Australian not-for-profit that connects
          remote and isolated communities with development resources and support services.
        </p>
        <div className="card" style={{ padding: 24 }}>
          <p style={{ margin: '0 0 12px', color: 'var(--sub)', fontSize: 14, lineHeight: 1.6 }}>
            LandChange guides communities through formal cooperative registration, so that
            funding and assistance can reach them directly and verifiably — reducing the
            fiduciary risk donors and partners take on. It works through a three-stage
            process: <strong style={{ color: 'var(--ink)' }}>identification</strong> of a
            community's needs and consent, <strong style={{ color: 'var(--ink)' }}>capacity
            building</strong> so the community can organise and participate on its own terms,
            and <strong style={{ color: 'var(--ink)' }}>brokered engagement</strong> that
            connects it to the right resources.
          </p>
          <p style={{ margin: 0, color: 'var(--sub)', fontSize: 14, lineHeight: 1.6 }}>
            Consent, cultural adaptation, and a clear audit trail run through every stage —
            UNIFIC's accounts, profile, and meeting tools exist to support exactly that kind
            of accountable, verifiable relationship between an organisation and the
            communities it serves.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <h2>Who we work with</h2>
      <p className="public-section-lead">
        UNIFIC partners with LandChange, an Australian not-for-profit that connects remote and
        isolated communities with development resources — guiding them through formal
        registration so support reaches them directly, verifiably, and with full consent.{' '}
        <a href="/about#landchange">Learn more</a>.
      </p>
    </div>
  )
}
