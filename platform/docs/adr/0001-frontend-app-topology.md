# ADR-0001: Frontend app topology

## Status

Accepted

## Context

The UNIFIC v2 rebuild directive asks for three distinct dashboards
(Client, Staff, Admin), each with its own login, and leaves open whether
that's one React/Vite app with three route trees or three separate
deployable apps.

The existing frontend (`platform/frontend/`) already partitions itself by
audience inside a single Vite SPA (`src/App.jsx`):

- A public/unauthenticated tree (`PublicLayout`: landing, about, contact,
  plus fully public routes like member registration and meeting-join
  links) — no auth provider mounted at all.
- A staff/admin tree (`AuthProvider` + `StaffArea`, gated by
  `ProtectedRoute`/`RequireAdmin`) mounting `StaffDashboardLayout` for
  admins and `StaffPortalLayout` for regular staff.
- A client tree (`ClientAuthProvider` + `ClientArea`, gated by
  `ScopeRoute`) mounting `ClientDashboardLayout` for both org owners and
  client-staff.

Each tree mounts its own auth context; `react-router-dom` v6 handles all
routing in one build. This has been working in production-shaped use
already — no separate deploy pipeline, no shared-component duplication
across repos.

## Decision

Keep the single Vite app with three route trees. Do not split into three
separate frontend apps/deployments, now or in later phases, unless a
concrete scaling or deploy reason emerges.

## Rationale

- Already proven and working in this codebase — zero migration cost, and
  the rebuild directive explicitly prefers boring, well-understood
  patterns over introducing new ones without cause.
- A shared component library (video-call components, layouts, the API
  client with token-refresh handling) would otherwise need duplication or
  a package-extraction step across three repos/apps — unjustified
  complexity at current team size and deploy target (a single droplet).
- One build/deploy pipeline, one dev server port, already referenced
  throughout `.env.example` and CORS config.

## Consequences

- **Known risk, not fixed here**: `App.jsx` documents that the staff and
  client `AuthProvider`s share a single in-memory access-token slot in
  `api/client.js` — safe today only because the two route subtrees never
  mount simultaneously. This is real but accepted debt; the frontend
  dashboards rebuild phase should either namespace token storage per
  audience or use two axios instances so the two trees are token-isolated
  even in principle, not just by mounting discipline.
- Bundle size grows with all three trees in one app. Vite's route-level
  code splitting is available if this becomes a real problem; not enabled
  now, not required by the directive.

## Alternatives considered

- **Three separate Vite apps** — rejected: deploy/CI complexity, shared
  component duplication, no concrete benefit at current scale.
- **Micro-frontend / module federation** — rejected: significant
  over-engineering for a three-audience app run off one backend process.
