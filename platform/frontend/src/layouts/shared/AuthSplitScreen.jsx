import React from 'react'
import { ShieldCheck, Lock, Users2 } from 'lucide-react'
import logo from '../../assets/logo.png'

const FEATURES = [
  {
    icon: Lock,
    title: 'Secure & private',
    desc: 'Your data is protected with enterprise-grade security.',
  },
  {
    icon: ShieldCheck,
    title: 'Verified & accountable',
    desc: 'Every action is logged with full transparency.',
  },
  {
    icon: Users2,
    title: 'Community powered',
    desc: 'Built for communities, by communities.',
  },
]

// Shared split-screen chrome for LoginPage.jsx / ClientLoginPage.jsx — the
// left branding panel is identical copy/markup on both; each page supplies
// its own form (and heading) as children, completely unchanged in logic.
// Below the `sm` breakpoint the branding panel collapses above the form
// (see .auth-split in tokens.css) rather than disappearing.
export default function AuthSplitScreen({ heading, subheading, children }) {
  return (
    <div className="auth-split">
      <div className="auth-split-brand">
        <div className="auth-split-wordmark">
          <img src={logo} alt="" width={36} height={36} style={{ display: 'block' }} />
          UNIFIC Platform
        </div>

        <div className="auth-split-copy">
          <h1>{heading}</h1>
          {subheading && <p>{subheading}</p>}
        </div>

        <div className="auth-split-features">
          {FEATURES.map((f) => (
            <div className="auth-split-feature" key={f.title}>
              <span className="auth-split-feature-icon">
                <f.icon size={16} />
              </span>
              <div>
                <div className="auth-split-feature-title">{f.title}</div>
                <div className="auth-split-feature-desc">{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="auth-split-form-side">{children}</div>
    </div>
  )
}
