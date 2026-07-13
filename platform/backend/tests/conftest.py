"""Integration test fixtures. Runs against the local docker-compose
Postgres (see ../docker-compose.yml) — not an isolated test database yet.
Each test that touches staff_user/staff_room_access should clean up
after itself via the `db_session` fixture's rollback-free delete, since
we share state with manual smoke testing during development.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import engine
from app.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_between_tests():
    """pytest-asyncio gives each test function its own event loop; a
    pooled asyncpg connection from a previous test's loop is unusable
    (and crashes on teardown) under a new one on Windows. Disposing the
    pool after every test forces fresh connections per loop.
    """
    yield
    await engine.dispose()
