# UNIFIC Platform

UNIFIC connects client organizations to their communities: staff manage
clients, clients manage members, and members are reached over WhatsApp
with AI-assisted translation, tone analysis, and reply drafting — plus a
LiveKit-based Meeting Room with live translation as a paid plugin.

This repository is being rewritten in place, phase by phase. Start here:

- [`docs/adr/`](docs/adr/) — current architecture decisions (frontend
  topology, job queue, target schema) with rationale.
- [`docs/PHASE_0_NOTES.md`](docs/PHASE_0_NOTES.md) — what's been built so
  far and what's next (later phases add their own `PHASE_N_NOTES.md`).
- [`docs/legacy/`](docs/legacy/) — the pre-rewrite architecture docs, kept
  as historical reference only.

## Layout

- `backend/` — FastAPI + async SQLAlchemy 2.0 + PostgreSQL 16 + Alembic.
- `frontend/` — React + Vite, one SPA with three route trees (client /
  staff / admin), see `docs/adr/0001-frontend-app-topology.md`.
- `docker-compose.yml` — postgres, redis, backend, worker.

## Local development

See `backend/.env.example` for required environment variables, and
`docs/PHASE_0_NOTES.md` for the current docker-compose / bare-process
setup instructions.
