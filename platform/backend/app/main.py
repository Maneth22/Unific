"""UNIFIC platform API. Rooms mount their own router; this file only
wires the app together — no business logic lives here.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.accounts.router import router as accounts_router
from app.auth.router import router as staff_auth_router
from app.config import settings
from app.meeting_room.router import client_router as meeting_room_client_router
from app.meeting_room.router import router as meeting_room_router
from app.middleware import SecurityHeadersMiddleware
from app.profiles.router import client_router as profiles_client_router
from app.profiles.router import router as profiles_router

app = FastAPI(
    title="UNIFIC Platform API",
    description="Task 1 (Accounts) · Task 2 (Profiles) · Task 3 (Meeting Room)",
    version="0.1.0",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(staff_auth_router)
app.include_router(accounts_router)
app.include_router(profiles_router)
app.include_router(profiles_client_router)
app.include_router(meeting_room_router)
app.include_router(meeting_room_client_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
