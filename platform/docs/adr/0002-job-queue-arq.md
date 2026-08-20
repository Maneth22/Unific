# ADR-0002: Background job queue — arq

## Status

Accepted

## Context

The rebuild directive requires LLM/WhatsApp/translation/report-generation
work to run as background jobs rather than inline in the request-response
cycle, with concurrency caps enforced per-org and globally, and with
workers that are horizontally scalable and stateless (Redis-backed
coordination, never in-process state).

Today the codebase has no task queue at all:

- `apscheduler>=3.10.4` runs a single in-process cron job
  (`app/agents/whatsapp_community/scheduler.py`, wired into `main.py`'s
  `lifespan`) for the WhatsApp end-of-day flush
  (`flush_service.py`) — nothing else goes through it.
- `redis>=5.0.0` is already a dependency, but purely as a cache/session
  store (`session_store.py` for same-day WhatsApp conversation state,
  plus rate-limit counters) — never as a broker.
- No Celery usage exists anywhere in the codebase or its history.
- `platform/README.md`'s "small droplet" section documents a real
  constraint that's separate from the job-queue question: the live-meeting
  agent orchestrator (`app/meeting_room/live_agents/orchestrator.py`)
  keeps an in-process `_running` registry, so the `backend` service itself
  must stay single-replica regardless of what background-job technology
  is chosen. A job queue's worker pool is additional capacity for
  background jobs, not a way to host live-meeting agents across replicas.

## Decision

arq.

## Rationale

- The rebuild directive's own stated preference is arq "unless the team
  already knows Celery" — no Celery usage exists in this codebase, so
  there's nothing to lose by choosing arq.
- arq is Redis-native and async-first, matching the codebase's async
  SQLAlchemy 2.0 / FastAPI / httpx stack throughout — no thread-pool
  bridging needed, unlike Celery's default sync worker model.
- arq needs no separate broker service or results-backend decision — it
  reuses the Redis container that's already running in
  `docker-compose.yml`, so adopting it costs zero new infrastructure.
- Smaller dependency surface than Celery's (kombu, billiard, etc.).

## Consequences

- Migrating the existing APScheduler EOD-flush cron job onto arq (arq
  supports cron jobs natively) is **deferred to the WhatsApp service
  rebuild phase**, once arq is actually wired into that pipeline — Phase 0
  only stands up the worker process skeleton (`app/worker.py`, a
  `backend`/`worker` docker-compose split) with a placeholder job.
- No new required environment variable: arq reuses the existing
  `settings.redis_url` from `app/config.py`.
- The `worker` service is meant to scale horizontally per the directive's
  non-negotiables; the `backend` service is not (see the `_running`
  registry constraint above) — this asymmetry is intentional and should
  stay documented wherever the two services are deployed.

## Alternatives considered

- **Celery** — rejected: sync-first, heavier dependency tree, no existing
  usage in this codebase to leverage.
- **RQ** — rejected: less async-native than arq (arq is effectively RQ's
  async-first successor, same author lineage).
- **APScheduler for everything** — rejected: doesn't satisfy the
  directive's stateless/horizontally-scalable non-negotiable; in-process
  cron can't coordinate across multiple worker replicas.
