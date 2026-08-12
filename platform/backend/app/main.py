"""UNIFIC platform API. Rooms mount their own router; this file only
wires the app together — no business logic lives here.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.accounts.router import router as accounts_router
from app.accounts.whatsapp_router import router as whatsapp_router
from app.agents.whatsapp_community.scheduler import start_scheduler
from app.auth.router import router as staff_auth_router
from app.config import settings
from app.core.providers.factory import get_video_provider
from app.core.rate_limit import limiter
from app.meeting_room.router import client_router as meeting_room_client_router
from app.meeting_room.router import public_router as meeting_room_public_router
from app.meeting_room.router import router as meeting_room_router
from app.middleware import SecurityHeadersMiddleware
from app.profiles.router import client_router as profiles_client_router
from app.profiles.router import client_staff_router as profiles_client_staff_router
from app.profiles.router import public_router as profiles_public_router
from app.profiles.router import router as profiles_router
from app.staff_directory.router import router as staff_directory_router
from app.tasking.router import router as tasking_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Forces the video-provider misconfiguration warnings (see factory.py) to
    # fire in deploy logs at boot, rather than lazily on the first meeting join.
    get_video_provider()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="UNIFIC Platform API",
    description="Task 1 (Accounts) · Task 2 (Profiles) · Task 3 (Meeting Room)",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(staff_auth_router)
app.include_router(accounts_router)
app.include_router(whatsapp_router)
app.include_router(profiles_router)
app.include_router(profiles_client_router)
app.include_router(profiles_client_staff_router)
app.include_router(profiles_public_router)
app.include_router(meeting_room_router)
app.include_router(meeting_room_client_router)
app.include_router(meeting_room_public_router)
app.include_router(staff_directory_router)
app.include_router(tasking_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
