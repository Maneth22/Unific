# UNIFIC Platform

Task 1 (Accounts) · Task 2 (Profiles) · Task 3 (Meeting Room) of the
UNIFIC eight-room system. See `docs/ARCHITECTURE.md` for how the rooms fit
together and how Tasks 4–8 slot in later.

Stack: FastAPI + async SQLAlchemy 2.0 + PostgreSQL (backend), React + Vite
(frontend). WhatsApp/translation/LLM integrations run behind provider
interfaces with mock implementations by default — no live credentials are
required for local development.

## Prerequisites

- Python 3.10+
- Node.js 18+
- Docker (for local Postgres) — or point `DATABASE_URL` at your own Postgres 16+ with the `ltree` extension available

## First-time setup

```bash
# 1. Start Postgres
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # then fill in JWT_SECRET / SECRETS_ENCRYPTION_KEY — see below
alembic upgrade head
python -m scripts.seed_rooms    # creates each room's account + agent sub-accounts
uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5183
```

Generate real local secrets rather than using the placeholders in
`.env.example`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"                    # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # SECRETS_ENCRYPTION_KEY
```

## First login

There is no self-registration. Bootstrap the first (superadmin) staff
account once — this endpoint refuses to run again after the first account
exists:

```bash
curl -X POST http://localhost:8000/api/auth/staff/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.org","password":"a-strong-password-12+chars","full_name":"Your Name"}'
```

Log in at `http://localhost:5183/login`. As superadmin you have every room;
use **Staff & Access** in the sidebar to provision additional staff and
grant them specific rooms.

## Local Postgres port

`docker-compose.yml` maps Postgres to host port **55432**, not the default
5432 — this machine may already have a native Postgres service bound to
5432 from another project. `DATABASE_URL` in `.env.example` already points
at 55432; adjust if your setup differs.

## Running tests

```bash
cd backend
pytest tests/ -v
```

Tests run against the same database as `DATABASE_URL` (there is no
separate test database yet) — they clean up the rows they create.

## Project layout

```
backend/app/
  core/         Task-0-equivalent shared infrastructure: staff+client auth,
                audit log, calendar, archive locker pattern, room accounts,
                the gate, provider interfaces — used by every room
  accounts/     Task 1
  profiles/     Task 2
  meeting_room/ Task 3
  auth/         staff login/session endpoints
frontend/src/
  rooms/        one folder per room's screens
  api/          one module per room's API client
  context/      AuthContext (staff session)
  routes/       ProtectedRoute / RoomRoute / ScopeRoute guards
docs/ARCHITECTURE.md   the room contract — read this before adding Task 4+
```

## WhatsApp / translation / LLM credentials

Not required for development — `WHATSAPP_PROVIDER=mock` (default) logs
sends and lets you simulate inbound messages from the Meeting Room's Chat
tab. To wire up the real WhatsApp Cloud API later, set
`WHATSAPP_PROVIDER=cloud_api` and fill in `WHATSAPP_CLOUD_API_TOKEN` /
`WHATSAPP_CLOUD_API_PHONE_NUMBER_ID` / `WHATSAPP_CLOUD_API_VERIFY_TOKEN` —
no application code changes are needed (see
`app/core/providers/cloud_api_whatsapp.py`).
